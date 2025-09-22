# AlphaCrypto_OrderBook.py
# BTC 1-hour directional signal using Order Book + Trade Flow analysis
# Runs independently from AlphaCrypto.py for parallel testing
# Data collection every 15 seconds, 1-hour predictions

import os, json, time, asyncio
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
import pytz
from collections import deque
import threading
import schedule
from concurrent.futures import ThreadPoolExecutor

import ccxt
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==============================
# Configuration
# ==============================
@dataclass
class OrderBookConfig:
    symbol: str = "BTC/USDT"
    prediction_hours: float = 1.0  # 1-hour predictions
    data_collection_interval: int = 60  # 60 seconds (1 minute)
    feature_window_minutes: int = 5  # 5-minute rolling windows
    signal_update_minutes: int = 5  # Update signals every 5 minutes
    orderbook_depth: int = 20  # Top 20 bid/ask levels
    trades_limit: int = 100  # Last 100 trades
    max_data_points: int = 60  # 1 hour of 1-minute data
    
    # Output files
    orderbook_data_file: str = "data/raw/orderbook_data.csv"
    trades_data_file: str = "data/raw/trades_data.csv"
    features_file: str = "data/processed/orderbook_features.csv"
    signals_file: str = "data/outputs/orderbook_signals.json"
    report_file: str = "data/outputs/reports/orderbook_report.md"
    
    # Feature calculation parameters
    imbalance_threshold: float = 0.1  # 10% imbalance threshold
    large_trade_threshold: float = 10000  # $10k+ trades
    spread_threshold: float = 0.0005  # 0.05% spread threshold

@dataclass
class OrderBookData:
    timestamp: datetime
    symbol: str
    bids: List[Tuple[float, float]]  # (price, volume)
    asks: List[Tuple[float, float]]
    spread: float
    mid_price: float
    best_bid: float
    best_ask: float

@dataclass
class TradeData:
    timestamp: datetime
    symbol: str
    price: float
    volume: float
    side: str  # 'buy' or 'sell'
    trade_id: str

@dataclass
class OrderBookFeatures:
    timestamp: datetime
    symbol: str
    
    # Order Book Imbalance Features
    volume_imbalance: float
    price_imbalance: float
    depth_imbalance: float
    
    # Spread Features
    spread_absolute: float
    spread_relative: float
    spread_volatility: float
    
    # Microstructure Features
    order_flow_rate: float
    cancellation_rate: float
    new_order_rate: float
    
    # Trade Flow Features
    trade_size_ratio: float
    buy_sell_pressure: float
    trade_frequency: float
    large_trade_ratio: float
    
    # Price Impact Features
    price_impact_01: float  # Volume needed for 0.1% move
    price_impact_05: float  # Volume needed for 0.5% move
    liquidity_concentration: float
    
    # Momentum Features
    orderbook_momentum: float
    trade_momentum: float
    microstructure_momentum: float

@dataclass
class PredictionSignal:
    timestamp: datetime
    symbol: str
    prediction_hours: float
    direction: str  # 'bullish', 'bearish', 'neutral'
    confidence: float
    features: Dict[str, float]
    reasoning: str

# ==============================
# Data Collection
# ==============================
class OrderBookCollector:
    def __init__(self, config: OrderBookConfig):
        self.config = config
        self.exchanges = self._init_exchanges()
        self.orderbook_buffer = deque(maxlen=config.max_data_points)
        self.trades_buffer = deque(maxlen=config.max_data_points)
        self.features_history = deque(maxlen=config.max_data_points)
        self.running = False
        
    def _init_exchanges(self) -> List[ccxt.Exchange]:
        """Initialize exchanges with error handling"""
        exchanges = []
        exchange_configs = [
            {'class': ccxt.coinbase, 'name': 'coinbase'},
            {'class': ccxt.kraken, 'name': 'kraken'},
            {'class': ccxt.bitfinex, 'name': 'bitfinex'},
            {'class': ccxt.bybit, 'name': 'bybit'}
        ]
        
        for ex_config in exchange_configs:
            try:
                exchange = ex_config['class']()
                exchange.load_markets()
                if self.config.symbol in exchange.markets:
                    exchanges.append(exchange)
                    print(f"✓ {ex_config['name']} initialized successfully")
                else:
                    print(f"⚠ {ex_config['name']} doesn't support {self.config.symbol}")
            except Exception as e:
                print(f"❌ Failed to initialize {ex_config['name']}: {e}")
                
        if not exchanges:
            raise Exception("No exchanges available for order book data")
        return exchanges
    
    def fetch_orderbook(self) -> Optional[OrderBookData]:
        """Fetch order book data from available exchanges"""
        for exchange in self.exchanges:
            try:
                orderbook = exchange.fetch_order_book(self.config.symbol, self.config.orderbook_depth)
                
                bids = [(float(price), float(volume)) for price, volume in orderbook['bids'][:self.config.orderbook_depth]]
                asks = [(float(price), float(volume)) for price, volume in orderbook['asks'][:self.config.orderbook_depth]]
                
                if not bids or not asks:
                    continue
                    
                best_bid = bids[0][0]
                best_ask = asks[0][0]
                spread = best_ask - best_bid
                mid_price = (best_bid + best_ask) / 2
                
                return OrderBookData(
                    timestamp=datetime.now(timezone.utc),
                    symbol=self.config.symbol,
                    bids=bids,
                    asks=asks,
                    spread=spread,
                    mid_price=mid_price,
                    best_bid=best_bid,
                    best_ask=best_ask
                )
                
            except Exception as e:
                print(f"❌ {exchange.id} orderbook fetch failed: {e}")
                continue
                
        return None
    
    def fetch_trades(self) -> List[TradeData]:
        """Fetch recent trades from available exchanges"""
        for exchange in self.exchanges:
            try:
                trades = exchange.fetch_trades(self.config.symbol, limit=self.config.trades_limit)
                
                trade_data = []
                for trade in trades:
                    trade_data.append(TradeData(
                        timestamp=datetime.fromtimestamp(trade['timestamp'] / 1000, tz=timezone.utc),
                        symbol=trade['symbol'],
                        price=float(trade['price']),
                        volume=float(trade['amount']),
                        side=trade['side'],
                        trade_id=str(trade['id'])
                    ))
                
                return trade_data
                
            except Exception as e:
                print(f"❌ {exchange.id} trades fetch failed: {e}")
                continue
                
        return []
    
    def collect_data(self):
        """Collect order book and trade data"""
        try:
            # Fetch order book data
            orderbook = self.fetch_orderbook()
            if orderbook:
                self.orderbook_buffer.append(orderbook)
                print(f"📊 Order book collected: {orderbook.mid_price:.2f} (spread: {orderbook.spread:.4f})")
            
            # Fetch trade data
            trades = self.fetch_trades()
            if trades:
                self.trades_buffer.extend(trades)
                print(f"💰 Trades collected: {len(trades)} trades")
            
        except Exception as e:
            print(f"❌ Data collection error: {e}")

# ==============================
# Feature Engineering
# ==============================
class OrderBookFeatureEngine:
    def __init__(self, config: OrderBookConfig):
        self.config = config
        self.feature_history = deque(maxlen=config.max_data_points)
    
    def calculate_imbalance_features(self, orderbook: OrderBookData) -> Dict[str, float]:
        """Calculate order book imbalance features"""
        bids = orderbook.bids
        asks = orderbook.asks
        
        if not bids or not asks:
            return {"volume_imbalance": 0.0, "price_imbalance": 0.0, "depth_imbalance": 0.0}
        
        # Volume imbalance
        bid_volume = sum(volume for _, volume in bids)
        ask_volume = sum(volume for _, volume in asks)
        total_volume = bid_volume + ask_volume
        volume_imbalance = (bid_volume - ask_volume) / total_volume if total_volume > 0 else 0.0
        
        # Price-weighted imbalance
        bid_price_volume = sum(price * volume for price, volume in bids)
        ask_price_volume = sum(price * volume for price, volume in asks)
        total_price_volume = bid_price_volume + ask_price_volume
        price_imbalance = (bid_price_volume - ask_price_volume) / total_price_volume if total_price_volume > 0 else 0.0
        
        # Depth imbalance (how many levels on each side)
        depth_imbalance = (len(bids) - len(asks)) / (len(bids) + len(asks)) if (len(bids) + len(asks)) > 0 else 0.0
        
        return {
            "volume_imbalance": volume_imbalance,
            "price_imbalance": price_imbalance,
            "depth_imbalance": depth_imbalance
        }
    
    def calculate_spread_features(self, orderbook: OrderBookData, recent_orderbooks: List[OrderBookData]) -> Dict[str, float]:
        """Calculate spread-related features"""
        spread_absolute = orderbook.spread
        spread_relative = spread_absolute / orderbook.mid_price if orderbook.mid_price > 0 else 0.0
        
        # Spread volatility over recent period
        if len(recent_orderbooks) > 1:
            recent_spreads = [ob.spread for ob in recent_orderbooks[-10:]]  # Last 10 data points
            spread_volatility = np.std(recent_spreads) if len(recent_spreads) > 1 else 0.0
        else:
            spread_volatility = 0.0
        
        return {
            "spread_absolute": spread_absolute,
            "spread_relative": spread_relative,
            "spread_volatility": spread_volatility
        }
    
    def calculate_trade_features(self, trades: List[TradeData], recent_trades: List[TradeData]) -> Dict[str, float]:
        """Calculate trade flow features"""
        if not trades:
            return {
                "trade_size_ratio": 0.0,
                "buy_sell_pressure": 0.0,
                "trade_frequency": 0.0,
                "large_trade_ratio": 0.0
            }
        
        # Trade size analysis
        large_trades = [t for t in trades if t.price * t.volume >= self.config.large_trade_threshold]
        large_trade_ratio = len(large_trades) / len(trades) if trades else 0.0
        
        # Buy/sell pressure
        buy_volume = sum(t.volume for t in trades if t.side == 'buy')
        sell_volume = sum(t.volume for t in trades if t.side == 'sell')
        total_volume = buy_volume + sell_volume
        buy_sell_pressure = (buy_volume - sell_volume) / total_volume if total_volume > 0 else 0.0
        
        # Trade frequency (trades per minute)
        if len(trades) > 1:
            time_span = (trades[-1].timestamp - trades[0].timestamp).total_seconds() / 60
            trade_frequency = len(trades) / time_span if time_span > 0 else 0.0
        else:
            trade_frequency = 0.0
        
        # Trade size ratio (large vs small)
        if trades:
            avg_trade_size = np.mean([t.price * t.volume for t in trades])
            large_avg_size = np.mean([t.price * t.volume for t in large_trades]) if large_trades else 0.0
            trade_size_ratio = large_avg_size / avg_trade_size if avg_trade_size > 0 else 0.0
        else:
            trade_size_ratio = 0.0
        
        return {
            "trade_size_ratio": trade_size_ratio,
            "buy_sell_pressure": buy_sell_pressure,
            "trade_frequency": trade_frequency,
            "large_trade_ratio": large_trade_ratio
        }
    
    def calculate_price_impact_features(self, orderbook: OrderBookData) -> Dict[str, float]:
        """Calculate price impact features"""
        bids = orderbook.bids
        asks = orderbook.asks
        
        if not bids or not asks:
            return {"price_impact_01": 0.0, "price_impact_05": 0.0, "liquidity_concentration": 0.0}
        
        mid_price = orderbook.mid_price
        
        # Calculate volume needed for 0.1% and 0.5% price moves
        target_01 = mid_price * 0.001  # 0.1%
        target_05 = mid_price * 0.005  # 0.5%
        
        # For upward moves (buying pressure)
        volume_01_up = 0.0
        volume_05_up = 0.0
        current_price = mid_price
        
        for price, volume in asks:
            if price <= mid_price + target_01:
                volume_01_up += volume
            if price <= mid_price + target_05:
                volume_05_up += volume
            else:
                break
        
        # For downward moves (selling pressure)
        volume_01_down = 0.0
        volume_05_down = 0.0
        
        for price, volume in bids:
            if price >= mid_price - target_01:
                volume_01_down += volume
            if price >= mid_price - target_05:
                volume_05_down += volume
            else:
                break
        
        # Take average of up and down
        price_impact_01 = (volume_01_up + volume_01_down) / 2
        price_impact_05 = (volume_05_up + volume_05_down) / 2
        
        # Liquidity concentration (how much volume is in top 5 levels)
        top_5_bid_volume = sum(volume for _, volume in bids[:5])
        top_5_ask_volume = sum(volume for _, volume in asks[:5])
        total_volume = sum(volume for _, volume in bids) + sum(volume for _, volume in asks)
        liquidity_concentration = (top_5_bid_volume + top_5_ask_volume) / total_volume if total_volume > 0 else 0.0
        
        return {
            "price_impact_01": price_impact_01,
            "price_impact_05": price_impact_05,
            "liquidity_concentration": liquidity_concentration
        }
    
    def calculate_microstructure_features(self, orderbook: OrderBookData, recent_orderbooks: List[OrderBookData]) -> Dict[str, float]:
        """Calculate microstructure features"""
        # Calculate order flow rate based on recent order book changes
        if len(recent_orderbooks) > 1:
            # Simple approximation: compare current vs previous order book depth
            current_depth = len(orderbook.bids) + len(orderbook.asks)
            prev_depth = len(recent_orderbooks[-2].bids) + len(recent_orderbooks[-2].asks)
            order_flow_rate = (current_depth - prev_depth) / 60.0  # Per second (60s intervals)
            
            # Cancellation rate (negative order flow)
            cancellation_rate = max(0, -order_flow_rate) / 60.0
            
            # New order rate (positive order flow)
            new_order_rate = max(0, order_flow_rate) / 60.0
        else:
            order_flow_rate = 0.0
            cancellation_rate = 0.0
            new_order_rate = 0.0
        
        return {
            "order_flow_rate": order_flow_rate,
            "cancellation_rate": cancellation_rate,
            "new_order_rate": new_order_rate
        }
    
    def calculate_momentum_features(self, current_features: Dict[str, float], recent_features: List[Dict[str, float]]) -> Dict[str, float]:
        """Calculate momentum features"""
        if not recent_features:
            return {"orderbook_momentum": 0.0, "trade_momentum": 0.0, "microstructure_momentum": 0.0}
        
        # Order book momentum (change in imbalance)
        if len(recent_features) > 1:
            recent_imbalances = [f.get("volume_imbalance", 0.0) for f in recent_features[-5:]]
            orderbook_momentum = np.mean(np.diff(recent_imbalances)) if len(recent_imbalances) > 1 else 0.0
        else:
            orderbook_momentum = 0.0
        
        # Trade momentum (change in buy/sell pressure)
        if len(recent_features) > 1:
            recent_pressure = [f.get("buy_sell_pressure", 0.0) for f in recent_features[-5:]]
            trade_momentum = np.mean(np.diff(recent_pressure)) if len(recent_pressure) > 1 else 0.0
        else:
            trade_momentum = 0.0
        
        # Microstructure momentum (combination of order book and trade changes)
        microstructure_momentum = (orderbook_momentum + trade_momentum) / 2
        
        return {
            "orderbook_momentum": orderbook_momentum,
            "trade_momentum": trade_momentum,
            "microstructure_momentum": microstructure_momentum
        }
    
    def calculate_all_features(self, orderbook: OrderBookData, trades: List[TradeData], 
                             recent_orderbooks: List[OrderBookData], recent_trades: List[TradeData]) -> OrderBookFeatures:
        """Calculate all order book features"""
        
        # Get recent features for momentum calculation
        recent_features = list(self.feature_history)[-10:]  # Last 10 feature sets
        
        # Calculate all feature groups
        imbalance_features = self.calculate_imbalance_features(orderbook)
        spread_features = self.calculate_spread_features(orderbook, recent_orderbooks)
        trade_features = self.calculate_trade_features(trades, recent_trades)
        price_impact_features = self.calculate_price_impact_features(orderbook)
        microstructure_features = self.calculate_microstructure_features(orderbook, recent_orderbooks)
        momentum_features = self.calculate_momentum_features({}, recent_features)
        
        # Combine all features
        all_features = {**imbalance_features, **spread_features, **trade_features, 
                       **price_impact_features, **microstructure_features, **momentum_features}
        
        features = OrderBookFeatures(
            timestamp=orderbook.timestamp,
            symbol=orderbook.symbol,
            **all_features
        )
        
        # Store in history
        self.feature_history.append(all_features)
        
        return features

# ==============================
# Prediction Logic
# ==============================
class OrderBookPredictor:
    def __init__(self, config: OrderBookConfig):
        self.config = config
        self.feature_weights = self._init_feature_weights()
    
    def _init_feature_weights(self) -> Dict[str, float]:
        """Initialize feature weights based on expected alpha"""
        return {
            # Tier 1: Highest alpha potential
            "volume_imbalance": 0.25,
            "microstructure_momentum": 0.20,
            "trade_size_ratio": 0.15,
            
            # Tier 2: High alpha potential
            "spread_relative": 0.10,
            "buy_sell_pressure": 0.10,
            "price_impact_01": 0.08,
            
            # Tier 3: Supporting signals
            "orderbook_momentum": 0.05,
            "trade_momentum": 0.05,
            "large_trade_ratio": 0.02
        }
    
    def calculate_signal_score(self, features: OrderBookFeatures) -> Tuple[float, str]:
        """Calculate prediction signal score and reasoning"""
        
        # Get feature values
        feature_dict = asdict(features)
        
        # Calculate weighted score
        total_score = 0.0
        total_weight = 0.0
        reasoning_parts = []
        
        for feature_name, weight in self.feature_weights.items():
            if feature_name in feature_dict:
                value = feature_dict[feature_name]
                if not np.isnan(value) and not np.isinf(value):
                    total_score += value * weight
                    total_weight += weight
                    
                    # Add to reasoning if significant
                    if abs(value) > 0.1:  # Significant threshold
                        direction = "bullish" if value > 0 else "bearish"
                        reasoning_parts.append(f"{feature_name}: {value:.3f} ({direction})")
        
        # Normalize score
        if total_weight > 0:
            normalized_score = total_score / total_weight
        else:
            normalized_score = 0.0
        
        # Determine direction and confidence
        if normalized_score > 0.1:
            direction = "bullish"
            confidence = min(0.9, 0.5 + abs(normalized_score) * 2)
        elif normalized_score < -0.1:
            direction = "bearish"
            confidence = min(0.9, 0.5 + abs(normalized_score) * 2)
        else:
            direction = "neutral"
            confidence = 0.3
        
        # Create reasoning
        reasoning = f"Score: {normalized_score:.3f}. " + "; ".join(reasoning_parts[:3])
        
        return normalized_score, direction, confidence, reasoning
    
    def generate_prediction(self, features: OrderBookFeatures) -> PredictionSignal:
        """Generate prediction signal from features"""
        
        score, direction, confidence, reasoning = self.calculate_signal_score(features)
        
        return PredictionSignal(
            timestamp=features.timestamp,
            symbol=features.symbol,
            prediction_hours=self.config.prediction_hours,
            direction=direction,
            confidence=confidence,
            features=asdict(features),
            reasoning=reasoning
        )

# ==============================
# Data Storage
# ==============================
class DataStorage:
    def __init__(self, config: OrderBookConfig):
        self.config = config
    
    def save_orderbook_data(self, orderbook: OrderBookData):
        """Save order book data to CSV"""
        data = {
            'timestamp': orderbook.timestamp.isoformat(),
            'symbol': orderbook.symbol,
            'mid_price': orderbook.mid_price,
            'best_bid': orderbook.best_bid,
            'best_ask': orderbook.best_ask,
            'spread': orderbook.spread,
            'bid_volume': sum(volume for _, volume in orderbook.bids),
            'ask_volume': sum(volume for _, volume in orderbook.asks),
            'bid_levels': len(orderbook.bids),
            'ask_levels': len(orderbook.asks)
        }
        
        df = pd.DataFrame([data])
        file_exists = os.path.exists(self.config.orderbook_data_file)
        df.to_csv(self.config.orderbook_data_file, mode='a', header=not file_exists, index=False)
    
    def save_trades_data(self, trades: List[TradeData]):
        """Save trade data to CSV"""
        if not trades:
            return
            
        data = []
        for trade in trades:
            data.append({
                'timestamp': trade.timestamp.isoformat(),
                'symbol': trade.symbol,
                'price': trade.price,
                'volume': trade.volume,
                'side': trade.side,
                'trade_id': trade.trade_id,
                'value': trade.price * trade.volume
            })
        
        df = pd.DataFrame(data)
        file_exists = os.path.exists(self.config.trades_data_file)
        df.to_csv(self.config.trades_data_file, mode='a', header=not file_exists, index=False)
    
    def save_features(self, features: OrderBookFeatures):
        """Save features to CSV"""
        data = asdict(features)
        data['timestamp'] = features.timestamp.isoformat()
        
        df = pd.DataFrame([data])
        file_exists = os.path.exists(self.config.features_file)
        df.to_csv(self.config.features_file, mode='a', header=not file_exists, index=False)
    
    def save_signal(self, signal: PredictionSignal):
        """Save prediction signal to JSON"""
        signal_data = asdict(signal)
        signal_data['timestamp'] = signal.timestamp.isoformat()
        
        # Convert any remaining datetime objects to ISO format
        def convert_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            return obj
        
        # Recursively convert datetime objects
        def clean_dict(d):
            if isinstance(d, dict):
                return {k: clean_dict(v) for k, v in d.items()}
            elif isinstance(d, list):
                return [clean_dict(item) for item in d]
            else:
                return convert_datetime(d)
        
        cleaned_data = clean_dict(signal_data)
        
        with open(self.config.signals_file, 'w') as f:
            json.dump(cleaned_data, f, indent=2)
    
    def generate_report(self, signal: PredictionSignal, features: OrderBookFeatures):
        """Generate markdown report"""
        report = f"""# Order Book Signal Report

**Timestamp:** {signal.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}  
**Symbol:** {signal.symbol}  
**Prediction Window:** {signal.prediction_hours} hours  
**Direction:** **{signal.direction.upper()}**  
**Confidence:** {signal.confidence:.2f}

## Key Features

### Order Book Imbalance
- **Volume Imbalance:** {features.volume_imbalance:.3f}
- **Price Imbalance:** {features.price_imbalance:.3f}
- **Depth Imbalance:** {features.depth_imbalance:.3f}

### Spread Analysis
- **Relative Spread:** {features.spread_relative:.4f} ({features.spread_relative*100:.2f}%)
- **Spread Volatility:** {features.spread_volatility:.6f}

### Trade Flow
- **Buy/Sell Pressure:** {features.buy_sell_pressure:.3f}
- **Large Trade Ratio:** {features.large_trade_ratio:.3f}
- **Trade Frequency:** {features.trade_frequency:.1f} trades/min

### Price Impact
- **0.1% Move Volume:** {features.price_impact_01:.2f} BTC
- **0.5% Move Volume:** {features.price_impact_05:.2f} BTC
- **Liquidity Concentration:** {features.liquidity_concentration:.3f}

### Momentum
- **Order Book Momentum:** {features.orderbook_momentum:.3f}
- **Trade Momentum:** {features.trade_momentum:.3f}
- **Microstructure Momentum:** {features.microstructure_momentum:.3f}

## Reasoning
{signal.reasoning}

---
*Generated by AlphaCrypto OrderBook v1.0*
"""
        
        with open(self.config.report_file, 'w') as f:
            f.write(report)

# ==============================
# Main Application
# ==============================
class OrderBookApp:
    def __init__(self):
        self.config = OrderBookConfig()
        self._ensure_directories()
        self.collector = OrderBookCollector(self.config)
        self.feature_engine = OrderBookFeatureEngine(self.config)
        self.predictor = OrderBookPredictor(self.config)
        self.storage = DataStorage(self.config)
        self.running = False
    
    def _ensure_directories(self):
        """Create necessary directories if they don't exist"""
        dirs = [
            "data/raw",
            "data/processed", 
            "data/outputs",
            "data/outputs/reports",
            "data/outputs/logs",
            "data/archive"
        ]
        for dir_path in dirs:
            os.makedirs(dir_path, exist_ok=True)
    
    def run_single_analysis(self):
        """Run a single analysis cycle"""
        print(f"\n🔍 Running Order Book Analysis - {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        
        try:
            # Collect data
            self.collector.collect_data()
            
            # Get recent data for feature calculation
            recent_orderbooks = list(self.collector.orderbook_buffer)[-10:]
            recent_trades = list(self.collector.trades_buffer)[-50:]
            
            if not recent_orderbooks:
                print("❌ No order book data available")
                return
            
            # Calculate features
            latest_orderbook = recent_orderbooks[-1]
            latest_trades = recent_trades[-10:] if recent_trades else []
            
            features = self.feature_engine.calculate_all_features(
                latest_orderbook, latest_trades, recent_orderbooks, recent_trades
            )
            
            # Generate prediction
            signal = self.predictor.generate_prediction(features)
            
            # Save data
            self.storage.save_orderbook_data(latest_orderbook)
            if latest_trades:
                self.storage.save_trades_data(latest_trades)
            self.storage.save_features(features)
            self.storage.save_signal(signal)
            self.storage.generate_report(signal, features)
            
            print(f"✅ Analysis complete: {signal.direction} (confidence: {signal.confidence:.2f})")
            print(f"📊 Features calculated: {len(asdict(features))} features")
            print(f"💾 Data saved to files")
            
        except Exception as e:
            print(f"❌ Analysis failed: {e}")
            import traceback
            traceback.print_exc()
    
    def start_continuous_collection(self):
        """Start continuous data collection and analysis"""
        print(f"🚀 Starting Order Book Data Collection")
        print(f"Collection interval: {self.config.data_collection_interval} seconds")
        print(f"Signal updates: every {self.config.signal_update_minutes} minutes")
        print(f"Prediction window: {self.config.prediction_hours} hours")
        print(f"Press Ctrl+C to stop")
        print(f"{'='*60}")
        
        self.running = True
        
        def collection_loop():
            while self.running:
                try:
                    self.collector.collect_data()
                    time.sleep(self.config.data_collection_interval)
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"❌ Collection error: {e}")
                    time.sleep(5)  # Wait before retry
        
        def analysis_loop():
            while self.running:
                try:
                    self.run_single_analysis()
                    time.sleep(self.config.signal_update_minutes * 60)  # Convert to seconds
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"❌ Analysis error: {e}")
                    time.sleep(60)  # Wait before retry
        
        # Start collection and analysis in separate threads
        collection_thread = threading.Thread(target=collection_loop, daemon=True)
        analysis_thread = threading.Thread(target=analysis_loop, daemon=True)
        
        collection_thread.start()
        analysis_thread.start()
        
        try:
            # Keep main thread alive
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n🛑 Stopping data collection...")
            self.running = False

# ==============================
# Main Entry Point
# ==============================
if __name__ == "__main__":
    import sys
    
    app = OrderBookApp()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--continuous":
        app.start_continuous_collection()
    else:
        print("Running single order book analysis...")
        print("Use 'python AlphaCrypto_OrderBook.py --continuous' for continuous collection")
        print("-" * 50)
        app.run_single_analysis()