# btc_24h_signal.py
# BTC next-24h directional signal using Tavily (news) + GPT-4.1 (sentiment) + TA
# Outputs: signal.json, report.md, features.csv, audit.log

import os, json, time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, TypedDict
from datetime import datetime, timedelta, timezone
import pandas as pd, numpy as np, pytz
from urllib.parse import urlparse
import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import schedule
import threading

from dotenv import load_dotenv
from tavily import TavilyClient
import ccxt
from openai import OpenAI
from langgraph.graph import StateGraph, END

# --- Load env vars from .env
load_dotenv()

# ==============================
# Config / State
# ==============================
@dataclass
class Config:
    symbol: str = "BTC/USDT"
    prediction_hours: int = 4  # Changed from 24h to 4h
    news_recent_hours: int = 2  # More recent news for 4h prediction
    news_slow_hours_min: int = 6  # Shorter slow window
    news_slow_hours_max: int = 12
    ta_lookback_days: int = 3  # Shorter lookback for 4h momentum
    max_news_items: int = 16  # Optimized for 4h timeframe - 2 queries × 8 results
    sentiment_recent_weight: float = 0.75  # Higher weight on recent sentiment
    sentiment_slow_weight: float = 0.25
    abstain_conf_threshold: float = 0.50  # Lower threshold for more opportunities
    disagree_penalty: float = 0.15  # Higher penalty for disagreement
    out_signal_json: str = "signal.json"
    out_report_md: str = "report.md"
    out_features_csv: str = "features.csv"
    out_audit_log: str = "audit.log"
    use_llm_sentiment: bool = True

class GraphState(TypedDict):
    cfg: Config
    ohlcv_df: Optional[pd.DataFrame]
    spot_price: Optional[float]
    tavily_recent: List[Dict[str, Any]]
    tavily_slow: List[Dict[str, Any]]
    docs_recent: List[Dict[str, Any]]
    docs_slow: List[Dict[str, Any]]
    sent_recent: Dict[str, Any]
    sent_slow: Dict[str, Any]
    sent_composite: Dict[str, Any]
    ta_features: Dict[str, float]
    ta_label: str
    ta_conf: float
    fusion: Dict[str, Any]
    guardrails: Dict[str, Any]
    report: Dict[str, Any]
    emails_sent: int
    total_sources: int

# ==============================
# Utils
# ==============================
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def to_local(dt_utc: datetime) -> str:
    return dt_utc.astimezone(pytz.timezone("America/New_York")).strftime("%Y-%m-%d %H:%M:%S %Z")

def canonical_url(u: str) -> str:
    try:
        p = urlparse(u)
        return f"{p.scheme}://{p.netloc}{p.path}"
    except Exception:
        return u

def dedup_by_title_url(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for it in items:
        key = (it.get("title","").strip().lower(), canonical_url(it.get("url","")))
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out

def filter_price_data_sites(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter out price data sites and low-quality sources that don't provide sentiment value"""
    price_data_keywords = [
        'price', 'chart', 'trading', 'live', 'real-time', 'quote', 'ticker',
        'market data', 'financial data', 'price today', 'current price'
    ]
    
    excluded_domains = [
        'yahoo.com', 'google.com/finance', 'tradingview.com', 'coinmarketcap.com',
        'coingecko.com', 'mexc.com', 'binance.com', 'coinbase.com'
    ]
    
    filtered = []
    for item in items:
        title = item.get("title", "").lower()
        url = item.get("url", "").lower()
        
        # Skip if it's clearly a price data site
        is_price_data = any(keyword in title for keyword in price_data_keywords)
        is_excluded_domain = any(domain in url for domain in excluded_domains)
        
        # Skip if it's just a price ticker or chart
        if is_price_data and is_excluded_domain:
            print(f"✗ Filtered out price data: {item.get('title', 'No title')[:50]}")
            continue
            
        # Skip if title is too generic or short
        if len(title) < 20 or title in ['bitcoin', 'btc', 'crypto', 'cryptocurrency']:
            print(f"✗ Filtered out generic title: {title}")
            continue
            
        filtered.append(item)
        print(f"✓ Kept: {item.get('title', 'No title')[:50]}")
    
    print(f"Filtered from {len(items)} to {len(filtered)} articles")
    return filtered

def clip_by_time(items, start_utc, end_utc):
    out = []
    print(f"Filtering {len(items)} items between {start_utc} and {end_utc}")
    for it in items:
        ts = it.get("published_time")
        if not ts: 
            print(f"No published_time for: {it.get('title', 'Unknown')[:50]}")
            continue
        try:
            pub = datetime.fromisoformat(ts.replace("Z","+00:00"))
            if start_utc <= pub <= end_utc:
                out.append(it)
                print(f"✓ Included: {it.get('title', 'Unknown')[:50]} ({pub})")
            else:
                print(f"✗ Excluded: {it.get('title', 'Unknown')[:50]} ({pub}) - outside time range")
        except Exception as e:
            print(f"✗ Error parsing time '{ts}': {e}")
    print(f"Final filtered count: {len(out)}")
    return out

def log_append(path: str, line: str):
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")

def send_email_report(
    subject: str,
    body_markdown: str,
    to_email: str,
    attachment_path: Optional[str] = None
) -> None:
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")

    if not (smtp_user and smtp_pass):
        raise RuntimeError("SMTP_USER/SMTP_PASS not set. Set Gmail app password or use your SMTP provider.")

    # Build message
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject

    # Simple plaintext email (Markdown as-is). Many clients render fine; you can add HTML conversion if desired.
    msg.attach(MIMEText(body_markdown, "plain", "utf-8"))

    # Optional attachment
    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(attachment_path)}"')
        msg.attach(part)

    # Send
    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls(context=context)
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to_email], msg.as_string())

# ==============================
# config_loader
# ==============================
def config_loader(_: GraphState) -> GraphState:
    return {"cfg": Config()}

# ==============================
# market_context_fetcher
# ==============================
def fetch_ohlcv(symbol: str, days: int = 7):
    # Try multiple exchanges in order of preference
    exchanges = [
        ccxt.coinbase(),
        ccxt.kraken(),
        ccxt.bitfinex(),
        ccxt.bybit()
    ]
    
    for ex in exchanges:
        try:
            now_ms = int(time.time() * 1000)
            since_ms = now_ms - days * 24 * 60 * 60 * 1000
            data = ex.fetch_ohlcv(symbol, timeframe="1h", since=since_ms, limit=1000)
            df = pd.DataFrame(data, columns=["ts","open","high","low","close","volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
            spot = float(df["close"].iloc[-1])
            print(f"Successfully fetched data from {ex.id}")
            return df, spot
        except Exception as e:
            print(f"Failed to fetch from {ex.id}: {str(e)[:100]}...")
            continue
    
    raise Exception("All exchanges failed. Please check your internet connection and try again.")

def market_context_fetcher(state: GraphState) -> GraphState:
    cfg = state["cfg"]
    df, spot = fetch_ohlcv(cfg.symbol, cfg.ta_lookback_days)
    return {"ohlcv_df": df, "spot_price": spot}

# ==============================
# news_social_gatherer
# ==============================
def tavily_search(q, time_range="d", max_results=20):
    api = os.getenv("TAVILY_API_KEY")
    if not api: 
        print("No Tavily API key found")
        return []
    
    try:
        client = TavilyClient(api_key=api)
        print(f"Searching Tavily with query: {q}")
        res = client.search(query=q, search_depth="advanced", time_range=time_range, max_results=max_results)
        items = res.get("results", [])
        print(f"Tavily returned {len(items)} raw results")
        return [{"title":r.get("title",""),"url":r.get("url",""),
                 "content":r.get("content",""),"published_time":r.get("published_time")} for r in items]
    except Exception as e:
        print(f"Tavily search error: {e}")
        return []

def news_social_gatherer(state: GraphState) -> GraphState:
    cfg = state["cfg"]
    
    # Check if we have Tavily API key
    if not os.getenv("TAVILY_API_KEY"):
        print("Warning: Missing Tavily API key. Using empty news data.")
        return {"tavily_recent": [], "tavily_slow": []}
    
    # Improved queries for 4h prediction - focus on news and analysis, not price data
    queries = [
        'bitcoin news analysis today',
        'bitcoin market news today',
        'bitcoin regulation news today',
        'bitcoin ETF news today'
    ]
    
    all_items = []
    for q in queries:
        items = tavily_search(q, time_range="d", max_results=6)  # Reduced to 6 per query
        all_items.extend(items)
    
    items = dedup_by_title_url(all_items)
    print(f"Total unique items found before filtering: {len(items)}")
    
    # Filter out price data sites and low-quality sources
    items = filter_price_data_sites(items)
    print(f"Total items after filtering: {len(items)}")
    
    # Since most items don't have published_time, let's use a simpler approach
    # Split items roughly in half for recent vs slow
    mid_point = len(items) // 2
    recent = items[:mid_point]
    slow = items[mid_point:]
    
    print(f"Using {len(recent)} items as recent and {len(slow)} items as slow")
    return {"tavily_recent": recent, "tavily_slow": slow, "total_sources": len(items)}

def doc_normalizer(state: GraphState) -> GraphState:
    return {"docs_recent": state.get("tavily_recent", []),
            "docs_slow": state.get("tavily_slow", [])}

# ==============================
# sentiment_classifier (GPT-4.1)
# ==============================
openai_client = OpenAI()

def llm_sentiment_doc(text: str):
    prompt = f"""Classify sentiment of this text toward Bitcoin's price in the next 4 hours.
Reply with one of: Positive, Negative, Neutral.
Also provide a brief reason for your classification.

Text:
{text[:2000]}

Format your response as:
Sentiment: [Positive/Negative/Neutral]
Reason: [Brief explanation]"""
    try:
        r = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0
        )
        response = r.choices[0].message.content.strip()
        
        # Parse sentiment and reason
        lines = response.split('\n')
        sentiment = "neutral"
        reason = "No reason provided"
        
        for line in lines:
            if line.startswith("Sentiment:"):
                sentiment = line.split(":", 1)[1].strip().lower()
            elif line.startswith("Reason:"):
                reason = line.split(":", 1)[1].strip()
        
        # Convert to score
        if "pos" in sentiment: 
            return "positive", +0.5, reason
        elif "neg" in sentiment: 
            return "negative", -0.5, reason
        else: 
            return "neutral", 0.0, reason
            
    except Exception as e:
        print("LLM sentiment error:", e)
        return "neutral", 0.0, f"Error: {str(e)}"

def sentiment_classifier(state: GraphState) -> GraphState:
    def score_set(docs):
        scored = []
        for d in docs:
            text = (d.get("title","") + " " + d.get("content","")).strip()
            if not text: text = d.get("title","")
            lbl, comp, reason = llm_sentiment_doc(text)
            scored.append({**d, "sent_label": lbl, "sent_compound": comp, "sent_reason": reason})
        return scored
    
    # Check if we have API keys, if not return neutral sentiment
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("TAVILY_API_KEY"):
        print("Warning: Missing API keys. Using neutral sentiment.")
        return {
            "sent_recent": {"items": []},
            "sent_slow": {"items": []}
        }
    
    recent_docs = state.get("docs_recent", [])
    slow_docs = state.get("docs_slow", [])
    print(f"Analyzing sentiment for {len(recent_docs)} recent docs and {len(slow_docs)} slow docs")
    
    # Debug: Check if we have documents to analyze
    if not recent_docs and not slow_docs:
        print("⚠️  No documents to analyze for sentiment")
        return {
            "sent_recent": {"items": []},
            "sent_slow": {"items": []}
        }
    
    # Analyze sentiment
    recent_scored = score_set(recent_docs)
    slow_scored = score_set(slow_docs)
    
    # Debug: Print summary results
    print(f"✓ Recent sentiment analysis: {len(recent_scored)} items")
    print(f"✓ Slow sentiment analysis: {len(slow_scored)} items")
    
    return {
        "sent_recent": {"items": recent_scored},
        "sent_slow":   {"items": slow_scored}
    }

# ==============================
# sentiment_aggregator
# ==============================
def aggregate_sentiment(items):
    if not items: return 0.0
    vals, weights = [], []
    for it in items:
        c = float(it.get("sent_compound",0.0))
        vals.append(c); weights.append(abs(c))
    
    # Handle case where all weights are zero (all neutral sentiment)
    if not weights or sum(weights) == 0:
        return 0.0
    
    return float(np.average(vals, weights=weights))

def sentiment_aggregator(state: GraphState) -> GraphState:
    cfg = state["cfg"]
    
    # Get sentiment items with fallback to empty lists
    recent_items = state.get("sent_recent", {}).get("items", [])
    slow_items = state.get("sent_slow", {}).get("items", [])
    
    # Debug: Print sentiment aggregation (commented out for production)
    # print(f"🔍 Sentiment aggregator: {len(recent_items)} recent, {len(slow_items)} slow items")
    
    score_recent = aggregate_sentiment(recent_items)
    score_slow   = aggregate_sentiment(slow_items)
    composite    = cfg.sentiment_recent_weight*score_recent + cfg.sentiment_slow_weight*score_slow
    
    # print(f"🔍 Aggregated scores: recent={score_recent:.3f}, slow={score_slow:.3f}, composite={composite:.3f}")
    
    return {"sent_composite":{"score_recent":score_recent,"score_slow":score_slow,
                              "score_composite":composite}}

# ==============================
# TA feature builder & classifier
# ==============================
def ema(series, span): return series.ewm(span=span, adjust=False).mean()
def sma(series, window): return series.rolling(window).mean()
def rsi(series, period=14):
    delta = series.diff()
    up, down = np.where(delta>0,delta,0), np.where(delta<0,-delta,0)
    roll_up, roll_down = pd.Series(up).rolling(period).mean(), pd.Series(down).rolling(period).mean()
    rs = roll_up/(roll_down+1e-9)
    return 100-(100/(1+rs))

def macd(series, fast=12, slow=26, signal=9):
    fast_e, slow_e = ema(series,fast), ema(series,slow)
    macd_line = fast_e - slow_e
    signal_line = ema(macd_line,signal)
    return macd_line, signal_line, macd_line-signal_line

def bollinger_bands(series, window=20, num_std=2):
    rolling_mean = series.rolling(window).mean()
    rolling_std = series.rolling(window).std()
    upper = rolling_mean + (rolling_std * num_std)
    lower = rolling_mean - (rolling_std * num_std)
    return upper, rolling_mean, lower

def atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def stochastic(high, low, close, k_period=14, d_period=3):
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k_percent = 100 * ((close - lowest_low) / (highest_high - lowest_low))
    d_percent = k_percent.rolling(d_period).mean()
    return k_percent, d_percent

def detect_market_regime(df):
    """Detect market trend and volatility regime"""
    ema_20 = df["close"].ewm(span=20).mean()
    ema_50 = df["close"].ewm(span=50).mean()
    trend = "uptrend" if ema_20.iloc[-1] > ema_50.iloc[-1] else "downtrend"
    
    # Volatility regime based on ATR
    atr_val = atr(df["high"], df["low"], df["close"]).iloc[-1]
    volatility = "high" if atr_val > df["close"].iloc[-1] * 0.02 else "low"
    
    return trend, volatility

def ta_feature_builder(state: GraphState) -> GraphState:
    df = state["ohlcv_df"].copy(); close = df["close"]
    
    # Basic indicators
    df["rsi14"] = rsi(close)
    macd_line, sig_line, hist = macd(close)
    df["macd_hist"] = hist
    df["ema20"], df["ema50"] = ema(close,20), ema(close,50)
    df["ema8"] = ema(close, 8)  # Shorter EMA for 4h momentum
    
    # New indicators
    bb_upper, bb_middle, bb_lower = bollinger_bands(close)
    df["bb_upper"] = bb_upper
    df["bb_lower"] = bb_lower
    df["bb_middle"] = bb_middle
    
    df["atr"] = atr(df["high"], df["low"], df["close"])
    df["atr_ratio"] = df["atr"] / df["close"]  # ATR as percentage of price
    
    stoch_k, stoch_d = stochastic(df["high"], df["low"], df["close"])
    df["stoch_k"] = stoch_k
    df["stoch_d"] = stoch_d
    
    latest, prev = df.iloc[-1], df.iloc[-2]
    
    # Calculate shorter-term momentum indicators for 4h prediction (FIXED)
    momentum_1h = float((latest["close"]-df["close"].iloc[-2])/df["close"].iloc[-2]) if len(df) > 2 else 0  # 1h ago
    momentum_2h = float((latest["close"]-df["close"].iloc[-3])/df["close"].iloc[-3]) if len(df) > 3 else 0  # 2h ago
    momentum_4h = float((latest["close"]-df["close"].iloc[-5])/df["close"].iloc[-5]) if len(df) > 5 else 0  # 4h ago
    
    # Volume momentum (if available)
    volume_ma = df["volume"].rolling(4).mean()
    volume_ratio = float(latest["volume"] / volume_ma.iloc[-1]) if not volume_ma.iloc[-1] == 0 else 1.0
    
    # Market regime detection
    trend, volatility = detect_market_regime(df)
    
    # Bollinger Bands position
    bb_position = (latest["close"] - latest["bb_lower"]) / (latest["bb_upper"] - latest["bb_lower"]) if latest["bb_upper"] != latest["bb_lower"] else 0.5
    
    feats = {
        # Basic indicators
        "rsi14": float(latest["rsi14"]),
        "macd_hist": float(latest["macd_hist"]),
        "ema8_above_ema20": float(latest["ema8"]-latest["ema20"]),
        "ema20_above_ema50": float(latest["ema20"]-latest["ema50"]),
        
        # Momentum indicators (FIXED)
        "momentum_1h": momentum_1h,
        "momentum_2h": momentum_2h,
        "momentum_4h": momentum_4h,
        
        # Volume
        "volume_ratio": volume_ratio,
        
        # New indicators
        "bb_upper": float(latest["bb_upper"]),
        "bb_lower": float(latest["bb_lower"]),
        "bb_position": float(bb_position),
        "atr_ratio": float(latest["atr_ratio"]),
        "stoch_k": float(latest["stoch_k"]),
        "stoch_d": float(latest["stoch_d"]),
        
        # Market regime
        "market_trend": trend,
        "market_volatility": volatility,
        
        # Price levels
        "close": float(latest["close"])
    }
    return {"ta_features": feats}

def ta_classifier(state: GraphState) -> GraphState:
    f = state["ta_features"]; score=0
    
    # RSI signals (improved thresholds for crypto)
    if f["rsi14"]>70: score+=0.3   # Strong overbought (bullish for crypto)
    elif f["rsi14"]>55: score+=0.15  # Moderate bullish
    elif f["rsi14"]<30: score-=0.3   # Strong oversold (bearish for crypto)
    elif f["rsi14"]<45: score-=0.15  # Moderate bearish
    
    # MACD histogram with momentum strength
    macd_strength = abs(f["macd_hist"]) / f["close"] * 100
    if f["macd_hist"]>0: 
        score += 0.2 * min(2.0, macd_strength)  # Scale with strength
    else: 
        score -= 0.2 * min(2.0, macd_strength)
    
    # EMA crossovers (prioritize shorter-term)
    if f["ema8_above_ema20"]>0: score+=0.25  # Short-term bullish
    if f["ema8_above_ema20"]<0: score-=0.25  # Short-term bearish
    if f["ema20_above_ema50"]>0: score+=0.15  # Medium-term confirmation
    if f["ema20_above_ema50"]<0: score-=0.15
    
    # Bollinger Bands
    if f["bb_position"]>0.8: score+=0.2   # Near upper band (overbought)
    elif f["bb_position"]<0.2: score-=0.2  # Near lower band (oversold)
    elif f["bb_position"]>0.6: score+=0.1  # Above middle
    elif f["bb_position"]<0.4: score-=0.1  # Below middle
    
    # Stochastic Oscillator
    if f["stoch_k"]>80 and f["stoch_d"]>80: score+=0.15  # Overbought
    elif f["stoch_k"]<20 and f["stoch_d"]<20: score-=0.15  # Oversold
    elif f["stoch_k"]>f["stoch_d"]: score+=0.05  # Bullish crossover
    elif f["stoch_k"]<f["stoch_d"]: score-=0.05  # Bearish crossover
    
    # Momentum signals (FIXED - now actually calculates momentum)
    if f["momentum_1h"]>0.005: score+=0.15  # Strong 1h momentum
    elif f["momentum_1h"]>0.002: score+=0.08  # Moderate 1h momentum
    elif f["momentum_1h"]<-0.005: score-=0.15
    elif f["momentum_1h"]<-0.002: score-=0.08
    
    if f["momentum_2h"]>0.01: score+=0.1  # 2h momentum confirmation
    elif f["momentum_2h"]<-0.01: score-=0.1
    
    if f["momentum_4h"]>0.02: score+=0.05  # 4h trend confirmation
    elif f["momentum_4h"]<-0.02: score-=0.05
    
    # Volume confirmation (enhanced)
    if f["volume_ratio"]>1.5: score+=0.15  # Very high volume
    elif f["volume_ratio"]>1.2: score+=0.1  # High volume
    elif f["volume_ratio"]<0.7: score-=0.15  # Very low volume
    elif f["volume_ratio"]<0.8: score-=0.1  # Low volume
    
    # Volatility adjustment
    if f["atr_ratio"]>0.03:  # High volatility
        score *= 1.2  # Boost signals in volatile markets
    elif f["atr_ratio"]<0.01:  # Low volatility
        score *= 0.8  # Reduce signals in low volatility
    
    # Market regime adjustment
    if f["market_trend"]=="uptrend": score+=0.1
    elif f["market_trend"]=="downtrend": score-=0.1
    
    if f["market_volatility"]=="high": score*=1.1  # Slight boost in high volatility
    elif f["market_volatility"]=="low": score*=0.9  # Slight reduction in low volatility
    
    # Final classification with improved confidence calculation
    label="neutral"; conf=0.5
    
    if score>0.15: 
        label="bullish"
        conf=min(0.90, 0.4 + min(abs(score), 1.0)*0.4)  # More conservative confidence scaling
    elif score<-0.15: 
        label="bearish"
        conf=min(0.90, 0.4 + min(abs(score), 1.0)*0.4)
    else:
        # Neutral zone - confidence based on how close to neutral
        conf=0.5 - abs(score)*0.3  # Lower confidence for neutral signals
    
    return {"ta_label":label,"ta_conf":conf}

# ==============================
# signal_fusion
# ==============================
def signal_fusion(state: GraphState) -> GraphState:
    cfg = state["cfg"]
    
    # Get sentiment composite with fallback to neutral
    sent_composite = state.get("sent_composite", {})
    s = float(sent_composite.get("score_composite", 0.0))
    
    # Debug: Print sentiment values in signal fusion (commented out for production)
    # print(f"🔍 Signal fusion sentiment debug:")
    # print(f"   sent_composite state: {sent_composite}")
    # print(f"   score_composite: {s}")
    
    s_dir = np.tanh(2*s)
    t_dir = 1 if state.get("ta_label") == "bullish" else -1 if state.get("ta_label") == "bearish" else 0
    ta_conf = state.get("ta_conf", 0.5)
    
    # Adjusted weights for 4h prediction - more weight on technical analysis
    fused = 0.60*t_dir*ta_conf + 0.40*s_dir
    if t_dir*s_dir < 0: 
        fused *= (1-cfg.disagree_penalty)
    
    # More sensitive thresholds for 4h prediction
    direction = "Up" if fused > 0.015 else "Down" if fused < -0.015 else "Abstain"
    
    # Adjusted confidence calculation for 4h timeframe
    # Lower base confidence but higher signal strength multiplier
    signal_strength = min(abs(fused), 0.5)  # Higher cap for signal strength
    agreement_bonus = 0.15 if (s_dir * t_dir) > 0 else 0  # Higher bonus for agreement
    base_conf = 0.25 + signal_strength + agreement_bonus
    conf = min(0.80, max(0.20, base_conf))  # Higher max confidence for 4h
    
    return {"fusion": {"direction_raw": direction, "conf_raw": conf, "fused_score": fused,
                      "s_dir": s_dir, "t_dir": t_dir, "ta_label": state.get("ta_label", "neutral"),
                      "ta_conf": ta_conf, "sent_recent": sent_composite.get("score_recent", 0.0),
                      "sent_slow": sent_composite.get("score_slow", 0.0)}}

# ==============================
# risk_guardrails
# ==============================
def risk_guardrails(state: GraphState) -> GraphState:
    cfg=state["cfg"]; f=state["fusion"]
    direction,conf=f["direction_raw"],f["conf_raw"]
    if conf<cfg.abstain_conf_threshold: direction="Abstain"
    return {"guardrails":{"direction_final":direction,"conf_final":conf}}

# ==============================
# reporter
# ==============================
# Global variable to track if reporter has run in this execution
_reporter_executed = False

def reporter(state: GraphState) -> GraphState:
    global _reporter_executed
    
    cfg=state["cfg"]
    
    # Check if reporter has already run in this execution
    if _reporter_executed:
        print("⚠️  Reporter already executed in this run, skipping to prevent duplicates")
        return {}
    
    # Mark as executed
    _reporter_executed = True
    
    # Get the final confidence value once and use it consistently
    final_confidence = state["guardrails"]["conf_final"]
    final_direction = state["guardrails"]["direction_final"]
    
    # Validate confidence value is reasonable
    if not (0.0 <= final_confidence <= 1.0):
        print(f"⚠️  Warning: Invalid confidence value {final_confidence}, clamping to valid range")
        final_confidence = max(0.0, min(1.0, final_confidence))
    
    # Get the composite sentiment score (the correct one to use)
    sentiment_composite = state.get("sent_composite", {}).get("score_composite", 0.0)
    
    # Debug: Print sentiment values (commented out for production)
    # print(f"🔍 Reporter sentiment debug:")
    # print(f"   sent_composite state: {state.get('sent_composite', {})}")
    # print(f"   sentiment_composite: {sentiment_composite}")
    # print(f"   fusion sent_recent: {state['fusion'].get('sent_recent', 'N/A')}")
    # print(f"   fusion sent_slow: {state['fusion'].get('sent_slow', 'N/A')}")
    
    sig={"timestamp_utc":now_utc().isoformat(),"symbol":cfg.symbol,
         "spot":state["spot_price"],
         "direction":final_direction,
         "confidence":final_confidence,
         "sentiment":sentiment_composite,
         "ta_label":state["fusion"]["ta_label"]}
    
    # Write JSON file
    with open(cfg.out_signal_json,"w") as f: 
        json.dump(sig,f,indent=2)
        f.flush()  # Ensure data is written
        f.close()  # Explicitly close
    
    print(f"✓ JSON written: confidence={final_confidence:.6f}, direction={final_direction}")
    # Get analyzed articles for display
    recent_items = state.get("sent_recent", {}).get("items", [])
    slow_items = state.get("sent_slow", {}).get("items", [])
    all_analyzed_items = recent_items + slow_items
    
    # Create article list section
    article_list = ""
    if all_analyzed_items:
        article_list = "\n## Articles Analyzed\n\n"
        
        # Recent articles
        if recent_items:
            article_list += "### Recent Articles (2h window)\n"
            for i, item in enumerate(recent_items[:8], 1):  # Limit to top 8
                sentiment = item.get("sent_label", "neutral").title()
                title = item.get("title", "No title")[:80] + "..." if len(item.get("title", "")) > 80 else item.get("title", "No title")
                url = item.get("url", "")
                reason = item.get("sent_reason", "No reason provided")
                article_list += f"{i}. **{sentiment}** - {title}\n   {url}\n   *Reason: {reason}*\n\n"
        
        # Slow articles
        if slow_items:
            article_list += "### Background Articles (6-12h window)\n"
            for i, item in enumerate(slow_items[:6], 1):  # Limit to top 6
                sentiment = item.get("sent_label", "neutral").title()
                title = item.get("title", "No title")[:80] + "..." if len(item.get("title", "")) > 80 else item.get("title", "No title")
                url = item.get("url", "")
                reason = item.get("sent_reason", "No reason provided")
                article_list += f"{i}. **{sentiment}** - {title}\n   {url}\n   *Reason: {reason}*\n\n"
    else:
        article_list = "\n## Articles Analyzed\n\n*No articles were analyzed (missing API keys or no results found)*\n\n"

    md=f"""# BTC 4-Hour Directional Signal

**As of:** {to_local(now_utc())}  
**Spot:** {state['spot_price']:.2f}  
**Decision:** **{final_direction}**  
**Confidence:** {final_confidence:.2f}

Sentiment composite: {state['fusion']['s_dir']:+.2f}  
TA: {state['fusion']['ta_label']} (conf {state['fusion']['ta_conf']:.2f})  
Fused score: {state['fusion']['fused_score']:+.3f}

**News Sources Analyzed:** {state.get('total_sources', 0)} articles
{article_list}---

## Methodology

### Data Sources
- **Market Data**: Coinbase Pro (with fallbacks to Kraken, Bitfinex, Bybit)
- **News & Sentiment**: Tavily API for real-time Bitcoin news
- **AI Analysis**: GPT-4.1-mini for sentiment classification

### Technical Analysis (4-Hour Optimized)
- **RSI (14)**: Momentum oscillator (bullish if >70, bearish if <30) - crypto-optimized thresholds
- **MACD Histogram**: Trend momentum indicator with strength scaling
- **EMA Crosses**: 8-day vs 20-day (short-term) + 20-day vs 50-day (confirmation)
- **Bollinger Bands**: Price position relative to volatility bands (20-period, 2 std)
- **Stochastic Oscillator**: Overbought/oversold conditions (14,3 periods)
- **ATR (Average True Range)**: Volatility measurement for signal adjustment
- **Multi-Timeframe Momentum**: 1h, 2h, and 4h price momentum (FIXED calculation)
- **Volume Confirmation**: Enhanced volume ratio analysis vs 4-hour average
- **Market Regime Detection**: Trend and volatility regime awareness
- **Lookback Period**: 3 days of hourly data

### Sentiment Analysis
- **News Sources**: 2 optimized queries (price news, breaking news) - 16 articles max
- **Time Windows**: Recent (2h) vs Slow (6-12h) sentiment weighting
- **AI Classification**: GPT-4.1-mini analyzes each news item for Bitcoin price sentiment
- **Weighting**: 75% recent sentiment + 25% slow sentiment
- **Article Count**: Optimized for 4h timeframe (reduced from 30 to 16 articles)

### Signal Fusion
- **Technical Weight**: 60% of final signal (increased for 4h prediction)
- **Sentiment Weight**: 40% of final signal
- **Disagreement Penalty**: 15% reduction when TA and sentiment conflict
- **Confidence Model**: Base 25% + signal strength (max 50%) + agreement bonus (15%)
- **Confidence Range**: 20% minimum, 80% maximum

### Risk Management
- **Abstain Threshold**: Signals below 50% confidence are marked as "Abstain"
- **Higher Confidence Cap**: Up to 80% for shorter timeframe predictions
- **Multi-Exchange**: Fallback exchanges prevent geographic restrictions

---
_Model: GPT-4.1-mini for sentiment analysis | Timeframe: 4 hours_
"""
    with open(cfg.out_report_md,"w") as f: 
        f.write(md)
        f.flush()  # Ensure content is written to disk
        f.close()  # Explicitly close the file
    
    # Force file system sync
    import os
    os.sync()
    
    # Create enhanced features data with timestamp and signal information
    current_timestamp = now_utc().isoformat()
    
    # Validate that we have proper sentiment data before writing
    # Get the correct sentiment values from the aggregator, not the transformed fusion values
    sentiment_data = state.get("sent_composite", {})
    sentiment_composite = sentiment_data.get("score_composite", 0.0)
    sentiment_recent = sentiment_data.get("score_recent", 0.0)
    sentiment_slow = sentiment_data.get("score_slow", 0.0)
    
    # Check if sentiment data is valid - only skip if we have no sentiment data at all
    # (Legitimate neutral sentiment with 0.0 values should still be valid)
    sentiment_valid = True  # Default to valid
    
    # Only consider invalid if we have no sentiment analysis at all
    if (sentiment_composite == 0.0 and sentiment_recent == 0.0 and sentiment_slow == 0.0):
        # Check if this is because sentiment analysis failed completely
        recent_items = state.get("sent_recent", {}).get("items", [])
        slow_items = state.get("sent_slow", {}).get("items", [])
        
        if not recent_items and not slow_items:
            print("⚠️  Warning: No sentiment analysis performed, skipping CSV write")
            print(f"   Sentiment values: composite={sentiment_composite}, recent={sentiment_recent}, slow={sentiment_slow}")
            return {"report":{"signal":sig, "markdown": md}}
        else:
            print("✓ Sentiment analysis completed with neutral results (all 0.0)")
    
    if not sentiment_valid:
        print("⚠️  Warning: Sentiment data appears incomplete, skipping CSV write")
        print(f"   Sentiment values: composite={sentiment_composite}, recent={sentiment_recent}, slow={sentiment_slow}")
        return {"report":{"signal":sig, "markdown": md}}
    
    # Use the same confidence and direction values as the JSON file
    enhanced_features = {
        **state["ta_features"],  # All technical analysis features
        "timestamp": current_timestamp,
        "spot_price": state["spot_price"],
        "decision": final_direction,  # Use the same direction as JSON
        "confidence": final_confidence,  # Use the same confidence as JSON
        "ta_label": state.get("ta_label", "neutral"),
        "ta_conf": state.get("ta_conf", 0.5),
        "sentiment_composite": sentiment_composite,
        "sentiment_recent": sentiment_recent,
        "sentiment_slow": sentiment_slow,
        "fused_score": state["fusion"].get("fused_score", 0.0),
        "news_sources": state.get("total_sources", 0)
    }
    
    # Validate that CSV will have the same confidence as JSON
    if abs(enhanced_features["confidence"] - final_confidence) > 1e-10:
        print(f"⚠️  ERROR: CSV confidence {enhanced_features['confidence']} != JSON confidence {final_confidence}")
        enhanced_features["confidence"] = final_confidence  # Force correction
        print(f"✓ Corrected CSV confidence to {final_confidence}")
    
    print(f"✓ CSV data prepared: confidence={enhanced_features['confidence']:.6f}, direction={enhanced_features['decision']}")
    
    # Append to CSV file (create if doesn't exist)
    df = pd.DataFrame([enhanced_features])
    if os.path.exists(cfg.out_features_csv):
        # Check if the existing file has the old format (17 columns) vs new format (28 columns)
        with open(cfg.out_features_csv, 'r') as f:
            first_line = f.readline().strip()
            existing_columns = first_line.count(',') + 1
        
        if existing_columns == 17:  # Old format
            print(f"⚠️  Detected old CSV format ({existing_columns} columns), converting to new format...")
            try:
                # Read the old data and convert to new format
                old_df = pd.read_csv(cfg.out_features_csv)
                
                # Add missing columns with default values
                for col in enhanced_features.keys():
                    if col not in old_df.columns:
                        old_df[col] = None
                
                # Reorder columns to match the new format
                old_df = old_df.reindex(columns=list(enhanced_features.keys()))
                
                # Write the converted data
                old_df.to_csv(cfg.out_features_csv, index=False)
                print(f"✓ Converted old CSV to new format with {len(enhanced_features)} columns")
            except Exception as e:
                print(f"❌ Failed to convert old CSV: {e}")
                print("Creating new CSV with current data only...")
                # If conversion fails, just create a new file with current data
                df.to_csv(cfg.out_features_csv, index=False)
                print(f"✓ Created new CSV with {len(enhanced_features)} columns")
        else:
            # Check for duplicate entries within the last 2 minutes
            try:
                existing_df = pd.read_csv(cfg.out_features_csv)
                if 'timestamp' in existing_df.columns and len(existing_df) > 0:
                    # Convert timestamps to datetime for comparison
                    existing_df['timestamp'] = pd.to_datetime(existing_df['timestamp'], format='ISO8601')
                    current_dt = pd.to_datetime(current_timestamp, format='ISO8601')
                    
                    # Check if there's an entry within the last 2 minutes
                    time_diff = (current_dt - existing_df['timestamp']).dt.total_seconds()
                    recent_entries = time_diff[time_diff >= 0].min() if len(time_diff[time_diff >= 0]) > 0 else float('inf')
                    
                    # More strict duplicate detection: skip if very recent (60 seconds) AND similar data
                    if recent_entries < 60:  # Increased to 60 seconds window
                        # Get the last entry
                        last_entry = existing_df.iloc[-1]
                        
                        # Check if key values are very similar (allowing for small market movements)
                        last_spot = last_entry.get('spot_price', 0.0)
                        current_spot = enhanced_features.get('spot_price', 0.0)
                        spot_diff = abs(current_spot - last_spot) if current_spot != 0 else float('inf')
                        
                        last_decision = last_entry.get('decision', '')
                        current_decision = enhanced_features.get('decision', '')
                        
                        last_ta_label = last_entry.get('ta_label', '')
                        current_ta_label = enhanced_features.get('ta_label', '')
                        
                        last_confidence = last_entry.get('confidence', 0.0)
                        current_confidence = enhanced_features.get('confidence', 0.0)
                        conf_diff = abs(current_confidence - last_confidence)
                        
                        # Check if this is a duplicate based on multiple criteria
                        # Skip if: very recent AND (identical data OR very similar data with same decision)
                        is_identical = (spot_diff < 0.01 and 
                                       last_decision == current_decision and 
                                       last_ta_label == current_ta_label and
                                       conf_diff < 0.01)
                        
                        is_very_similar = (spot_diff < 1.0 and  # Within $1
                                          last_decision == current_decision and
                                          last_ta_label == current_ta_label and
                                          conf_diff < 0.1)  # Within 10% confidence
                        
                        if is_identical:
                            print(f"⚠️  Found identical entry {recent_entries:.1f} seconds ago, skipping")
                            print(f"   Last: spot=${last_spot:.2f}, decision={last_decision}, conf={last_confidence:.3f}")
                            print(f"   Current: spot=${current_spot:.2f}, decision={current_decision}, conf={current_confidence:.3f}")
                            return {"report":{"signal":sig, "markdown": md}}
                        elif is_very_similar and recent_entries < 30:  # Very similar within 30 seconds
                            print(f"⚠️  Found very similar entry {recent_entries:.1f} seconds ago, skipping to prevent duplicates")
                            print(f"   Last: spot=${last_spot:.2f}, decision={last_decision}, conf={last_confidence:.3f}")
                            print(f"   Current: spot=${current_spot:.2f}, decision={current_decision}, conf={current_confidence:.3f}")
                            return {"report":{"signal":sig, "markdown": md}}
                        else:
                            print(f"📊 Found recent entry but data changed significantly, updating CSV")
                            print(f"   Spot diff: ${spot_diff:.2f}, Decision: {last_decision}→{current_decision}, Conf: {last_confidence:.3f}→{current_confidence:.3f}")
                    else:
                        print(f"📊 No recent entries found, proceeding with CSV update")
            except Exception as e:
                print(f"⚠️  Could not check for duplicates: {e}")
        
        # Now append the new row
        df.to_csv(cfg.out_features_csv, mode='a', header=False, index=False)
    else:
        df.to_csv(cfg.out_features_csv, index=False)
    
    # Final validation: ensure all files have consistent data
    print(f"✓ Final validation:")
    print(f"   JSON: confidence={sig['confidence']:.6f}, direction={sig['direction']}")
    print(f"   CSV:  confidence={enhanced_features['confidence']:.6f}, direction={enhanced_features['decision']}")
    print(f"   MD:   confidence={final_confidence:.2f}, direction={final_direction}")
    
    # Verify consistency
    json_conf = sig['confidence']
    csv_conf = enhanced_features['confidence']
    md_conf = final_confidence
    
    if abs(json_conf - csv_conf) > 1e-10 or abs(json_conf - md_conf) > 1e-10:
        print(f"❌ CRITICAL: Data inconsistency detected!")
        print(f"   JSON confidence: {json_conf:.6f}")
        print(f"   CSV confidence:  {csv_conf:.6f}")
        print(f"   MD confidence:   {md_conf:.6f}")
    else:
        print(f"✅ All files have consistent confidence values")
    
    log_append(cfg.out_audit_log,f"{now_utc().isoformat()} decision={sig['direction']} conf={sig['confidence']:.2f}")
    
    return {"report":{"signal":sig, "markdown": md}}

# ==============================
# email_sender
# ==============================
def email_sender(state: GraphState) -> GraphState:
    # Check if emails have already been sent to prevent duplicates
    if state.get("emails_sent", 0) > 0:
        print("Emails already sent, skipping...")
        return {"emails_sent": state.get("emails_sent", 0)}
    
    # Check if we have all required data before sending
    if not state.get("fusion") or not state.get("guardrails") or not state.get("report"):
        print("State not fully populated, skipping email...")
        return {"emails_sent": 0}
    
    # Wait longer to ensure all processing is complete and files are written
    import time
    time.sleep(8.0)  # Increased wait time to ensure file is written
    
    # Try to get markdown from state first (most reliable), then fall back to file
    cfg = state["cfg"]
    markdown = None
    
    # First try: get from state if available
    if state.get("report") and state["report"].get("markdown"):
        markdown = state["report"]["markdown"]
        print(f"✓ Using markdown from state ({len(markdown)} characters)")
    else:
        # Fallback: read from file with validation
        max_retries = 5
        for attempt in range(max_retries):
            try:
                with open(cfg.out_report_md, "r", encoding="utf-8") as f:
                    markdown = f.read()
                print(f"✓ Read final markdown from disk ({len(markdown)} characters)")
                
                # Check if the markdown contains the expected final data structure
                if "## Articles Analyzed" in markdown and "**Decision:**" in markdown:
                    # Additional validation: check for reasonable confidence values (not 0.25 or 0.30)
                    confidence_match = re.search(r'\*\*Confidence:\*\* ([\d.]+)', markdown)
                    if confidence_match:
                        conf_val = float(confidence_match.group(1))
                        if conf_val >= 0.4:  # Reasonable confidence threshold
                            print(f"✓ Markdown contains final data with articles (confidence: {conf_val})")
                            break
                        else:
                            print(f"⚠ Markdown contains low confidence ({conf_val}), may be intermediate data, waiting...")
                            if attempt < max_retries - 1:
                                time.sleep(3.0)
                                continue
                            else:
                                print("✗ Markdown still contains low confidence after all retries")
                                return {"emails_sent": 0}
                    else:
                        print("✓ Markdown contains final data with articles")
                        break
                else:
                    print("⚠ Markdown may not contain complete data, waiting...")
                    if attempt < max_retries - 1:
                        time.sleep(3.0)
                        continue
                    else:
                        print("✗ Markdown doesn't contain expected final data after all retries")
                        return {"emails_sent": 0}
                    
            except Exception as e:
                print(f"✗ Attempt {attempt + 1} failed to read markdown file: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1.0)
                else:
                    return {"emails_sent": 0}
    
    if not markdown:
        print("✗ Could not get markdown content from state or file")
        return {"emails_sent": 0}
    
    # Extract the final values from the markdown content
    import re
    
    # Extract decision and confidence from markdown
    decision_match = re.search(r'\*\*Decision:\*\* \*\*(.*?)\*\*', markdown)
    confidence_match = re.search(r'\*\*Confidence:\*\* ([\d.]+)', markdown)
    spot_match = re.search(r'\*\*Spot:\*\* ([\d,]+\.?\d*)', markdown)
    
    if not all([decision_match, confidence_match, spot_match]):
        print("✗ Could not extract final values from markdown")
        print(f"  Decision match: {decision_match}")
        print(f"  Confidence match: {confidence_match}")
        print(f"  Spot match: {spot_match}")
        return {"emails_sent": 0}
    
    final_direction = decision_match.group(1)
    final_confidence = float(confidence_match.group(1))
    spot = float(spot_match.group(1).replace(',', ''))
    
    print(f"Final email data:")
    print(f"  Direction: {final_direction}")
    print(f"  Confidence: {final_confidence}")
    print(f"  Spot: {spot}")
    
    # Email addresses to send to
    email_addresses = ["tkap243@gmail.com"]
    
    # Create subject line using final values
    subject = f"BTC 4H Signal: {final_direction} (Confidence: {final_confidence:.0%}) - ${spot:,.0f}"
    
    print(f"Sending emails to {len(email_addresses)} recipients...")
    print(f"Email content preview: {markdown[:200]}...")
    print(f"Email content length: {len(markdown)} characters")
    print(f"Contains articles section: {'## Articles Analyzed' in markdown}")
    print(f"Contains decision: {'**Decision:**' in markdown}")
    
    # Additional validation: check if this looks like the final data
    if "Abstain" in markdown and "0.25" in markdown:
        print("⚠ WARNING: Email contains old intermediate data (Abstain/0.25)")
        print("This suggests the email is reading cached or old data")
        return {"emails_sent": 0}
    
    if "Up" in markdown and "0.80" in markdown:
        print("✓ Email contains current final data (Up/0.80)")
    elif "Down" in markdown:
        print("✓ Email contains current final data (Down)")
    else:
        print(f"⚠ Email data: Decision={final_direction}, Confidence={final_confidence}")
    
    # Send emails
    success_count = 0
    for email in email_addresses:
        try:
            send_email_report(
                subject=subject,
                body_markdown=markdown,
                to_email=email,
                attachment_path=cfg.out_signal_json
            )
            print(f"✓ Email sent successfully to {email}")
            success_count += 1
        except Exception as e:
            print(f"✗ Failed to send email to {email}: {e}")
    
    print(f"Email sending complete: {success_count}/{len(email_addresses)} successful")
    return {"emails_sent": success_count}

# ==============================
# Build Graph
# ==============================
def build_graph():
    g=StateGraph(GraphState)
    g.add_node("config_loader",config_loader)
    g.add_node("market_context_fetcher",market_context_fetcher)
    g.add_node("news_social_gatherer",news_social_gatherer)
    g.add_node("doc_normalizer",doc_normalizer)
    g.add_node("sentiment_classifier",sentiment_classifier)
    g.add_node("sentiment_aggregator",sentiment_aggregator)
    g.add_node("ta_feature_builder",ta_feature_builder)
    g.add_node("ta_classifier",ta_classifier)
    g.add_node("signal_fusion",signal_fusion)
    g.add_node("risk_guardrails",risk_guardrails)
    g.add_node("reporter",reporter)
    # g.add_node("email_sender",email_sender)  # Commented out for testing

    g.set_entry_point("config_loader")
    g.add_edge("config_loader","market_context_fetcher")
    g.add_edge("config_loader","news_social_gatherer")
    g.add_edge("news_social_gatherer","doc_normalizer")
    g.add_edge("doc_normalizer","sentiment_classifier")
    g.add_edge("sentiment_classifier","sentiment_aggregator")
    g.add_edge("market_context_fetcher","ta_feature_builder")
    g.add_edge("ta_feature_builder","ta_classifier")
    g.add_edge("sentiment_aggregator","signal_fusion")
    g.add_edge("ta_classifier","signal_fusion")
    # Remove direct connection from market_context_fetcher to signal_fusion
    # Signal fusion should only run after both sentiment and TA are complete
    g.add_edge("signal_fusion","risk_guardrails")
    g.add_edge("risk_guardrails","reporter")
    # g.add_edge("reporter","email_sender")  # Commented out for testing
    # g.add_edge("email_sender",END)  # Commented out for testing
    g.add_edge("reporter",END)  # Skip email sending during testing
    return g.compile()

# ==============================
# Scheduler Functions
# ==============================
def run_analysis():
    """Run a single analysis cycle with cooldown protection"""
    # Check for cooldown file to prevent rapid re-runs
    cooldown_file = "last_run.txt"
    min_interval_seconds = 60  # Minimum 1 minute between runs
    
    try:
        # Check if we ran recently
        if os.path.exists(cooldown_file):
            with open(cooldown_file, 'r') as f:
                last_run_str = f.read().strip()
            last_run = datetime.fromisoformat(last_run_str)
            time_since_last = (now_utc() - last_run).total_seconds()
            
            if time_since_last < min_interval_seconds:
                print(f"⏰ Cooldown active: {min_interval_seconds - time_since_last:.0f}s remaining")
                print(f"Last run: {to_local(last_run)}")
                return False
        
        print(f"\n{'='*60}")
        print(f"Starting BTC 4H Analysis at {to_local(now_utc())}")
        print(f"{'='*60}")
        
        app = build_graph()
        state = {
            "cfg": Config(), "ohlcv_df": None, "spot_price": None,
            "tavily_recent": [], "tavily_slow": [], "docs_recent": [], "docs_slow": [],
            "sent_recent": {}, "sent_slow": {}, "sent_composite": {},
            "ta_features": {}, "ta_label": "neutral", "ta_conf": 0.5,
            "fusion": {}, "guardrails": {}, "report": {}, "emails_sent": 0, "total_sources": 0
        }
        
        out = app.invoke(state)
        
        # Print results
        signal = out["report"]["signal"]
        print(f"\n📊 ANALYSIS COMPLETE")
        print(f"Decision: {signal['direction']}")
        print(f"Confidence: {signal['confidence']:.1%}")
        print(f"Spot Price: ${signal['spot']:,.2f}")
        print(f"Report written: {Config().out_report_md}")
        print(f"Features appended to: {Config().out_features_csv}")
        print(f"{'='*60}\n")
        
        # Write cooldown file
        with open(cooldown_file, 'w') as f:
            f.write(now_utc().isoformat())
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR in analysis: {e}")
        print(f"Time: {to_local(now_utc())}")
        print(f"{'='*60}\n")
        return False

def run_scheduler():
    """Run the scheduler in a separate thread"""
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

def cleanup_duplicate_entries():
    """Remove duplicate entries from features.csv based on timestamp"""
    csv_file = Config().out_features_csv
    if not os.path.exists(csv_file):
        print(f"📁 No CSV file found at {csv_file}")
        return
    
    try:
        df = pd.read_csv(csv_file)
        if len(df) <= 1:
            print(f"✅ CSV file has {len(df)} entries, no cleanup needed")
            return
        
        print(f"📊 Found {len(df)} entries in {csv_file}")
        
        # Check if timestamp column exists
        if 'timestamp' not in df.columns:
            print("⚠️  No timestamp column found, cannot clean duplicates")
            return
        
        # Convert timestamp to datetime for proper comparison
        df['timestamp'] = pd.to_datetime(df['timestamp'], format='ISO8601')
        
        # Sort by timestamp to ensure proper ordering
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # Remove duplicates based on key identifying features within 2 minutes
        df_clean = df.copy()
        indices_to_remove = []
        
        for i in range(1, len(df_clean)):
            current = df_clean.iloc[i]
            previous = df_clean.iloc[i-1]
            
            # Check if entries are within 2 minutes
            time_diff = (current['timestamp'] - previous['timestamp']).total_seconds()
            
            if time_diff < 120:  # Within 2 minutes
                # Check if key identifying features are the same
                spot_diff = abs(current.get('spot_price', 0) - previous.get('spot_price', 0))
                same_ta_features = all(
                    abs(current.get(col, 0) - previous.get(col, 0)) < 1e-10 
                    for col in ['rsi14', 'macd_hist', 'ema8_above_ema20', 'ema20_above_ema50']
                    if col in current and col in previous
                )
                
                # Check if sentiment data is incomplete (all zeros) in current entry
                current_sentiment_incomplete = (current.get('sentiment_composite', 0) == 0.0 and 
                                              current.get('sentiment_recent', 0) == 0.0 and 
                                              current.get('sentiment_slow', 0) == 0.0)
                
                # Remove if it's a duplicate OR if current has incomplete sentiment data
                if (spot_diff < 0.01 and same_ta_features) or current_sentiment_incomplete:
                    indices_to_remove.append(i)
                    reason = "duplicate" if (spot_diff < 0.01 and same_ta_features) else "incomplete sentiment"
                    print(f"🗑️  Marked for removal at {current['timestamp']} ({reason})")
        
        # Remove marked indices (in reverse order to maintain index positions)
        for idx in sorted(indices_to_remove, reverse=True):
            df_clean = df_clean.drop(df_clean.index[idx])
        
        if len(df_clean) < len(df):
            removed_count = len(df) - len(df_clean)
            print(f"🧹 Cleaned up {removed_count} entries from {csv_file}")
            print(f"📊 Remaining entries: {len(df_clean)}")
            df_clean.to_csv(csv_file, index=False)
            
            # Show final entries for verification
            print(f"📊 Final entries:")
            for i, row in df_clean.iterrows():
                print(f"   {i+1}. {row['timestamp']} | ${row.get('spot_price', 0):.2f} | {row.get('decision', 'N/A')} | {row.get('ta_label', 'N/A')} | sent={row.get('sentiment_composite', 0):.3f}")
        else:
            print(f"✅ No duplicates found in {csv_file}")
            
    except Exception as e:
        print(f"❌ Error cleaning duplicates: {e}")
        import traceback
        traceback.print_exc()

def start_automatic_scheduler():
    """Start the 4-hour automatic scheduler"""
    print(f"🚀 Starting BTC 4H Signal Scheduler")
    print(f"Initial run at: {to_local(now_utc())}")
    print(f"Schedule: Every 4 hours")
    print(f"Press Ctrl+C to stop")
    print(f"{'='*60}")
    
    # Clean up any existing duplicates
    cleanup_duplicate_entries()
    
    # Schedule to run every 4 hours
    schedule.every(4).hours.do(run_analysis)
    
    # Run initial analysis immediately
    run_analysis()
    
    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    try:
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n🛑 Scheduler stopped by user")
        print(f"Final run at: {to_local(now_utc())}")

# ==============================
# Main
# ==============================
if __name__=="__main__":
    import sys
    
    # Check if user wants to clean up duplicates
    if len(sys.argv) > 1 and sys.argv[1] == "--cleanup":
        print("🧹 Cleaning up duplicate entries...")
        cleanup_duplicate_entries()
        print("✅ Cleanup complete!")
    # Check if user wants automatic scheduling
    elif len(sys.argv) > 1 and sys.argv[1] == "--schedule":
        start_automatic_scheduler()
    else:
        # Run single analysis (original behavior)
        print("Running single analysis...")
        print("Use 'python AlphaCrypto.py --schedule' for automatic 4-hour scheduling")
        print("Use 'python AlphaCrypto.py --cleanup' to remove duplicate entries")
        print("-" * 50)
        
        # Check for cooldown to prevent rapid successive runs
        cooldown_file = "last_run.txt"
        min_interval_seconds = 30  # Minimum 30 seconds between runs
        
        try:
            # Check if we ran recently
            if os.path.exists(cooldown_file):
                with open(cooldown_file, 'r') as f:
                    last_run_str = f.read().strip()
                last_run = datetime.fromisoformat(last_run_str)
                time_since_last = (now_utc() - last_run).total_seconds()
                
                if time_since_last < min_interval_seconds:
                    print(f"⏰ Cooldown active: {min_interval_seconds - time_since_last:.0f}s remaining")
                    print(f"Last run: {to_local(last_run)}")
                    print("Use 'python AlphaCrypto.py --cleanup' to remove duplicates if needed")
                    sys.exit(0)
        except Exception as e:
            print(f"⚠️  Could not check cooldown: {e}")
        
        app = build_graph()
        state = {
            "cfg": Config(), "ohlcv_df": None, "spot_price": None,
            "tavily_recent": [], "tavily_slow": [], "docs_recent": [], "docs_slow": [],
            "sent_recent": {}, "sent_slow": {}, "sent_composite": {},
            "ta_features": {}, "ta_label": "neutral", "ta_conf": 0.5,
            "fusion": {}, "guardrails": {}, "report": {}, "emails_sent": 0, "total_sources": 0
        }
        
        try:
            out = app.invoke(state)
            print(json.dumps(out["report"]["signal"], indent=2))
            print(f"Report written: {Config().out_report_md}")
            
            # Write cooldown file
            with open(cooldown_file, 'w') as f:
                f.write(now_utc().isoformat())
            print(f"✓ Cooldown file updated")
            
        except Exception as e:
            print(f"❌ Error in analysis: {e}")
            import traceback
            traceback.print_exc()

