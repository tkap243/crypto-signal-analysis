# AlphaCrypto_Derivatives.py
# BTC derivative data collection and analysis for enhanced predictions
# Collects futures, funding rates, and options data every 15 minutes
# Generates 1-hour directional signals using derivative market structure

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
class DerivativeConfig:
    symbol: str = "BTC/USDT"
    prediction_hours: float = 1.0  # 1-hour predictions
    data_collection_interval: int = 900  # 15 minutes (900 seconds)
    feature_window_minutes: int = 60  # 1-hour rolling windows
    signal_update_minutes: int = 15  # Update signals every 15 minutes
    max_data_points: int = 96  # 24 hours of 15-minute data
    
    # Output files
    derivative_data_file: str = "data/raw/derivative_data.csv"
    features_file: str = "data/processed/derivative_features.csv"
    signals_file: str = "data/outputs/derivative_signals.json"
    report_file: str = "data/outputs/reports/derivative_report.md"
    
    # Feature calculation parameters
    basis_threshold: float = 0.001  # 0.1% basis threshold
    funding_rate_threshold: float = 0.0001  # 0.01% funding rate threshold
    oi_change_threshold: float = 0.05  # 5% OI change threshold

@dataclass
class FuturesData:
    timestamp: datetime
    symbol: str
    exchange: str
    futures_price: float
    spot_price: float
    basis: float  # (futures - spot) / spot
    basis_percent: float  # basis * 100
    open_interest: float
    volume_24h: float
    volume_change_24h: float

@dataclass
class FundingRateData:
    timestamp: datetime
    symbol: str
    exchange: str
    funding_rate: float
    funding_rate_percent: float
    next_funding_time: datetime
    predicted_funding_rate: float

@dataclass
class OptionsData:
    timestamp: datetime
    symbol: str
    exchange: str
    put_call_ratio: float
    implied_volatility: float
    skew: float  # Put skew - Call skew
    total_volume: float
    open_interest: float

@dataclass
class DerivativeFeatures:
    timestamp: datetime
    symbol: str
    
    # Futures Features
    avg_basis: float
    basis_volatility: float
    basis_momentum: float
    oi_change_24h: float
    oi_momentum: float
    volume_ratio: float
    
    # Funding Rate Features
    avg_funding_rate: float
    funding_rate_volatility: float
    funding_rate_momentum: float
    funding_rate_spread: float  # Max - Min across exchanges
    
    # Options Features (if available)
    put_call_ratio: float
    implied_vol: float
    vol_skew: float
    
    # Composite Features
    derivative_sentiment: float  # -1 to 1
    derivative_confidence: float  # 0 to 1
    market_structure_score: float  # Overall market structure health

@dataclass
class DerivativeSignal:
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
class DerivativeCollector:
    def __init__(self, config: DerivativeConfig):
        self.config = config
        self.exchanges = self._init_exchanges()
        self.futures_buffer = deque(maxlen=config.max_data_points)
        self.funding_buffer = deque(maxlen=config.max_data_points)
        self.options_buffer = deque(maxlen=config.max_data_points)
        self.features_history = deque(maxlen=config.max_data_points)
        self.running = False
        
    def _init_exchanges(self) -> List[Dict[str, Any]]:
        """Initialize exchanges with derivative support"""
        exchanges = []
        exchange_configs = [
            {'class': ccxt.binance, 'name': 'binance', 'has_futures': True, 'has_funding': True},
            {'class': ccxt.okx, 'name': 'okx', 'has_futures': True, 'has_funding': True},
            {'class': ccxt.bybit, 'name': 'bybit', 'has_futures': True, 'has_funding': True},
            {'class': ccxt.bitmex, 'name': 'bitmex', 'has_futures': True, 'has_funding': True},
            # Removed Deribit - requires account setup and was using mock data
        ]
        
        for ex_config in exchange_configs:
            try:
                exchange = ex_config['class']()
                exchange.load_markets()
                
                # Check if exchange supports our symbol
                if self.config.symbol in exchange.markets:
                    exchanges.append({
                        'exchange': exchange,
                        'name': ex_config['name'],
                        'has_futures': ex_config.get('has_futures', False),
                        'has_funding': ex_config.get('has_funding', False),
                        'has_options': ex_config.get('has_options', False)
                    })
                    print(f"✓ {ex_config['name']} initialized successfully")
                else:
                    print(f"⚠ {ex_config['name']} doesn't support {self.config.symbol}")
            except Exception as e:
                print(f"❌ Failed to initialize {ex_config['name']}: {e}")
                
        if not exchanges:
            raise Exception("No exchanges available for derivative data")
        return exchanges
    
    def fetch_futures_data(self) -> List[FuturesData]:
        """Fetch futures data from available exchanges"""
        futures_data = []
        
        for ex_info in self.exchanges:
            if not ex_info['has_futures']:
                continue
                
            try:
                exchange = ex_info['exchange']
                
                # Try to get futures ticker
                try:
                    futures_ticker = exchange.fetch_ticker(f"{self.config.symbol}:USDT")
                except:
                    # Fallback to regular symbol if futures not available
                    futures_ticker = exchange.fetch_ticker(self.config.symbol)
                
                # Get spot price for basis calculation
                spot_ticker = exchange.fetch_ticker(self.config.symbol)
                
                futures_price = float(futures_ticker.get('last', 0) or 0)
                spot_price = float(spot_ticker.get('last', 0) or 0)
                
                if futures_price == 0 or spot_price == 0:
                    print(f"⚠ {ex_info['name']} invalid price data (futures: {futures_price}, spot: {spot_price}), skipping")
                    continue
                basis = (futures_price - spot_price) / spot_price
                basis_percent = basis * 100
                
                # Get open interest and volume (if available)
                try:
                    oi_data = exchange.fetch_open_interest(self.config.symbol)
                    open_interest = float(oi_data.get('openInterestAmount', 0))
                    if open_interest == 0:
                        # Try alternative OI field names
                        open_interest = float(oi_data.get('openInterest', 0))
                except:
                    # For BitMEX, try to get OI from ticker
                    try:
                        ticker_oi = futures_ticker.get('openInterest', 0)
                        open_interest = float(ticker_oi) if ticker_oi else 0.0
                    except:
                        open_interest = 0.0
                
                volume_24h = float(futures_ticker.get('quoteVolume', 0))
                
                futures_data.append(FuturesData(
                    timestamp=datetime.now(timezone.utc),
                    symbol=self.config.symbol,
                    exchange=ex_info['name'],
                    futures_price=futures_price,
                    spot_price=spot_price,
                    basis=basis,
                    basis_percent=basis_percent,
                    open_interest=open_interest,
                    volume_24h=volume_24h,
                    volume_change_24h=0.0  # Would need historical data
                ))
                
                print(f"📊 {ex_info['name']} futures: ${futures_price:.2f} (basis: {basis_percent:.3f}%)")
                
            except Exception as e:
                print(f"❌ {ex_info['name']} futures fetch failed: {e}")
                continue
                
        return futures_data
    
    def fetch_funding_rates(self) -> List[FundingRateData]:
        """Fetch funding rates from available exchanges"""
        funding_data = []
        
        for ex_info in self.exchanges:
            if not ex_info['has_funding']:
                continue
                
            try:
                exchange = ex_info['exchange']
                
                # Try different symbol formats for funding rates
                funding_symbols = [
                    self.config.symbol,
                    f"{self.config.symbol}:USDT",
                    f"{self.config.symbol.replace('/', '')}USDT"
                ]
                
                funding_rate = None
                for symbol in funding_symbols:
                    try:
                        funding_rate = exchange.fetch_funding_rate(symbol)
                        break
                    except:
                        continue
                
                if not funding_rate:
                    print(f"⚠ {ex_info['name']} no funding rate data available")
                    continue
                
                rate = float(funding_rate.get('fundingRate', 0))
                rate_percent = rate * 100
                
                # Handle different timestamp formats
                funding_timestamp = funding_rate.get('fundingTimestamp', 0)
                if funding_timestamp:
                    if funding_timestamp > 1e10:  # Already in milliseconds
                        next_funding = datetime.fromtimestamp(funding_timestamp / 1000, tz=timezone.utc)
                    else:  # Already in seconds
                        next_funding = datetime.fromtimestamp(funding_timestamp, tz=timezone.utc)
                else:
                    next_funding = datetime.now(timezone.utc)
                
                funding_data.append(FundingRateData(
                    timestamp=datetime.now(timezone.utc),
                    symbol=self.config.symbol,
                    exchange=ex_info['name'],
                    funding_rate=rate,
                    funding_rate_percent=rate_percent,
                    next_funding_time=next_funding,
                    predicted_funding_rate=rate  # Simplified
                ))
                
                print(f"💰 {ex_info['name']} funding: {rate_percent:.4f}%")
                
            except Exception as e:
                print(f"❌ {ex_info['name']} funding fetch failed: {e}")
                continue
                
        return funding_data
    
    def fetch_options_data(self) -> List[OptionsData]:
        """Fetch options data from available exchanges - Currently disabled"""
        # Options data collection disabled - requires account setup for real data
        # and mock data was not providing value
        print("📈 Options data collection disabled - requires account setup")
        return []
    
    def collect_data(self):
        """Collect all derivative data"""
        try:
            # Fetch futures data
            futures_data = self.fetch_futures_data()
            if futures_data:
                self.futures_buffer.extend(futures_data)
                print(f"📊 Futures collected: {len(futures_data)} exchanges")
            
            # Fetch funding rates
            funding_data = self.fetch_funding_rates()
            if funding_data:
                self.funding_buffer.extend(funding_data)
                print(f"💰 Funding rates collected: {len(funding_data)} exchanges")
            
            # Skip options data collection (disabled)
            # options_data = self.fetch_options_data()
            # if options_data:
            #     self.options_buffer.extend(options_data)
            #     print(f"📈 Options collected: {len(options_data)} exchanges")
            
        except Exception as e:
            print(f"❌ Derivative data collection error: {e}")

# ==============================
# Feature Engineering
# ==============================
class DerivativeFeatureEngine:
    def __init__(self, config: DerivativeConfig):
        self.config = config
        self.feature_history = deque(maxlen=config.max_data_points)
    
    def calculate_futures_features(self, futures_data: List[FuturesData], 
                                 recent_futures: List[FuturesData]) -> Dict[str, float]:
        """Calculate futures-based features"""
        if not futures_data:
            return {
                "avg_basis": 0.0, "basis_volatility": 0.0, "basis_momentum": 0.0,
                "oi_change_24h": 0.0, "oi_momentum": 0.0, "volume_ratio": 0.0
            }
        
        # Average basis across exchanges
        basis_values = [f.basis for f in futures_data]
        avg_basis = np.mean(basis_values)
        
        # Basis volatility (use historical data if only 1 exchange)
        if len(basis_values) > 1:
            basis_volatility = np.std(basis_values)
        else:
            # Use recent historical basis data for volatility calculation
            recent_basis = [f.basis for f in recent_futures[-10:] if hasattr(f, 'basis')]
            basis_volatility = np.std(recent_basis) if len(recent_basis) > 1 else 0.0
        
        # Basis momentum (change over time)
        if len(recent_futures) > 1:
            recent_basis = [f.basis for f in recent_futures[-10:]]  # Last 10 data points
            basis_momentum = np.mean(np.diff(recent_basis)) if len(recent_basis) > 1 else 0.0
        else:
            basis_momentum = 0.0
        
        # Open interest change (simplified)
        oi_values = [f.open_interest for f in futures_data if f.open_interest > 0]
        oi_change_24h = np.mean(oi_values) if oi_values else 0.0
        
        # OI momentum
        if len(recent_futures) > 1:
            recent_oi = [f.open_interest for f in recent_futures[-10:] if f.open_interest > 0]
            oi_momentum = np.mean(np.diff(recent_oi)) if len(recent_oi) > 1 else 0.0
        else:
            oi_momentum = 0.0
        
        # Volume ratio (current vs average)
        volume_values = [f.volume_24h for f in futures_data if f.volume_24h > 0]
        if volume_values and len(recent_futures) > 1:
            recent_volumes = [f.volume_24h for f in recent_futures[-10:] if f.volume_24h > 0]
            avg_volume = np.mean(recent_volumes) if recent_volumes else 1.0
            volume_ratio = np.mean(volume_values) / avg_volume if avg_volume > 0 else 1.0
        else:
            volume_ratio = 1.0
        
        return {
            "avg_basis": avg_basis,
            "basis_volatility": basis_volatility,
            "basis_momentum": basis_momentum,
            "oi_change_24h": oi_change_24h,
            "oi_momentum": oi_momentum,
            "volume_ratio": volume_ratio
        }
    
    def calculate_funding_features(self, funding_data: List[FundingRateData],
                                 recent_funding: List[FundingRateData]) -> Dict[str, float]:
        """Calculate funding rate-based features"""
        if not funding_data:
            return {
                "avg_funding_rate": 0.0, "funding_rate_volatility": 0.0,
                "funding_rate_momentum": 0.0, "funding_rate_spread": 0.0
            }
        
        # Average funding rate
        rate_values = [f.funding_rate for f in funding_data]
        avg_funding_rate = np.mean(rate_values)
        
        # Funding rate volatility
        funding_rate_volatility = np.std(rate_values) if len(rate_values) > 1 else 0.0
        
        # Funding rate momentum
        if len(recent_funding) > 1:
            recent_rates = [f.funding_rate for f in recent_funding[-10:]]
            funding_rate_momentum = np.mean(np.diff(recent_rates)) if len(recent_rates) > 1 else 0.0
        else:
            funding_rate_momentum = 0.0
        
        # Funding rate spread (max - min)
        funding_rate_spread = max(rate_values) - min(rate_values) if len(rate_values) > 1 else 0.0
        
        return {
            "avg_funding_rate": avg_funding_rate,
            "funding_rate_volatility": funding_rate_volatility,
            "funding_rate_momentum": funding_rate_momentum,
            "funding_rate_spread": funding_rate_spread
        }
    
    def calculate_options_features(self, options_data: List[OptionsData]) -> Dict[str, float]:
        """Calculate options-based features - Currently disabled"""
        # Options data collection disabled, return neutral values
        return {
            "put_call_ratio": 1.0,  # Neutral P/C ratio
            "implied_vol": 0.0,     # No IV data
            "vol_skew": 0.0         # No skew data
        }
    
    def calculate_composite_features(self, futures_features: Dict[str, float],
                                   funding_features: Dict[str, float],
                                   options_features: Dict[str, float]) -> Dict[str, float]:
        """Calculate composite derivative features"""
        
        # Derivative sentiment score (-1 to 1)
        # Positive basis = bullish, negative = bearish
        basis_sentiment = np.tanh(futures_features["avg_basis"] * 100)  # Scale basis
        
        # Funding rate sentiment (positive rates = bearish for longs)
        funding_sentiment = -np.tanh(funding_features["avg_funding_rate"] * 1000)  # Scale funding rate
        
        # Options sentiment (P/C ratio > 1 = bearish)
        options_sentiment = -np.tanh((options_features["put_call_ratio"] - 1) * 2)
        
        # Weighted derivative sentiment (options disabled, focus on futures and funding)
        derivative_sentiment = (0.7 * basis_sentiment + 0.3 * funding_sentiment)
        
        # Confidence based on data quality and signal strength (options disabled)
        data_quality = min(1.0, (len(futures_features) + len(funding_features)) / 2)
        signal_strength = min(1.0, abs(derivative_sentiment) * 2)
        derivative_confidence = data_quality * signal_strength
        
        # Market structure score (health of derivative markets)
        structure_score = 1.0 - (futures_features["basis_volatility"] + funding_features["funding_rate_volatility"]) / 2
        structure_score = max(0.0, min(1.0, structure_score))
        
        return {
            "derivative_sentiment": derivative_sentiment,
            "derivative_confidence": derivative_confidence,
            "market_structure_score": structure_score
        }
    
    def calculate_all_features(self, futures_data: List[FuturesData],
                             funding_data: List[FundingRateData],
                             options_data: List[OptionsData],
                             recent_futures: List[FuturesData],
                             recent_funding: List[FundingRateData]) -> DerivativeFeatures:
        """Calculate all derivative features"""
        
        # Calculate feature groups
        futures_features = self.calculate_futures_features(futures_data, recent_futures)
        funding_features = self.calculate_funding_features(funding_data, recent_funding)
        options_features = self.calculate_options_features(options_data)
        composite_features = self.calculate_composite_features(futures_features, funding_features, options_features)
        
        # Combine all features
        all_features = {**futures_features, **funding_features, **options_features, **composite_features}
        
        features = DerivativeFeatures(
            timestamp=datetime.now(timezone.utc),
            symbol=self.config.symbol,
            **all_features
        )
        
        # Store in history
        self.feature_history.append(all_features)
        
        return features

# ==============================
# Prediction Logic
# ==============================
class DerivativePredictor:
    def __init__(self, config: DerivativeConfig):
        self.config = config
        self.feature_weights = self._init_feature_weights()
    
    def _init_feature_weights(self) -> Dict[str, float]:
        """Initialize feature weights for derivative signals"""
        return {
            # Tier 1: Highest alpha potential
            "avg_basis": 0.30,
            "derivative_sentiment": 0.25,
            "basis_momentum": 0.15,
            
            # Tier 2: High alpha potential
            "avg_funding_rate": 0.10,
            "funding_rate_momentum": 0.08,
            "oi_momentum": 0.07,
            
            # Tier 3: Supporting signals
            "put_call_ratio": 0.03,
            "implied_vol": 0.02
        }
    
    def generate_prediction(self, features: DerivativeFeatures) -> DerivativeSignal:
        """Generate prediction signal from derivative features"""
        
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
                    if abs(value) > 0.01:  # Significant threshold
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
        
        return DerivativeSignal(
            timestamp=features.timestamp,
            symbol=features.symbol,
            prediction_hours=self.config.prediction_hours,
            direction=direction,
            confidence=confidence,
            features=feature_dict,
            reasoning=reasoning
        )

# ==============================
# Data Storage
# ==============================
class DerivativeDataStorage:
    def __init__(self, config: DerivativeConfig):
        self.config = config
    
    def save_derivative_data(self, futures_data: List[FuturesData], 
                           funding_data: List[FundingRateData],
                           options_data: List[OptionsData]):
        """Save raw derivative data to CSV"""
        all_data = []
        
        # Add futures data
        for f in futures_data:
            all_data.append({
                'timestamp': f.timestamp.isoformat(),
                'type': 'futures',
                'exchange': f.exchange,
                'symbol': f.symbol,
                'futures_price': f.futures_price,
                'spot_price': f.spot_price,
                'basis': f.basis,
                'basis_percent': f.basis_percent,
                'open_interest': f.open_interest,
                'volume_24h': f.volume_24h,
                'put_call_ratio': '',  # Empty for futures
                'implied_volatility': '',  # Empty for futures
                'skew': ''  # Empty for futures
            })
        
        # Add funding data
        for f in funding_data:
            all_data.append({
                'timestamp': f.timestamp.isoformat(),
                'type': 'funding',
                'exchange': f.exchange,
                'symbol': f.symbol,
                'futures_price': '',  # Empty for funding
                'spot_price': '',  # Empty for funding
                'basis': '',  # Empty for funding
                'basis_percent': '',  # Empty for funding
                'open_interest': '',  # Empty for funding
                'volume_24h': '',  # Empty for funding
                'funding_rate': f.funding_rate,
                'funding_rate_percent': f.funding_rate_percent,
                'next_funding_time': f.next_funding_time.isoformat(),
                'put_call_ratio': '',  # Empty for funding
                'implied_volatility': '',  # Empty for funding
                'skew': ''  # Empty for funding
            })
        
        # Skip options data (disabled)
        # for o in options_data:
        #     all_data.append({...})
        
        if all_data:
            df = pd.DataFrame(all_data)
            file_exists = os.path.exists(self.config.derivative_data_file)
            df.to_csv(self.config.derivative_data_file, mode='a', header=not file_exists, index=False)
    
    def save_features(self, features: DerivativeFeatures):
        """Save features to CSV"""
        data = asdict(features)
        data['timestamp'] = features.timestamp.isoformat()
        
        df = pd.DataFrame([data])
        file_exists = os.path.exists(self.config.features_file)
        df.to_csv(self.config.features_file, mode='a', header=not file_exists, index=False)
    
    def save_signal(self, signal: DerivativeSignal):
        """Save prediction signal to JSON"""
        signal_data = asdict(signal)
        signal_data['timestamp'] = signal.timestamp.isoformat()
        
        # Convert any remaining datetime objects to ISO format
        def convert_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            return obj
        
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
    
    def generate_report(self, signal: DerivativeSignal, features: DerivativeFeatures):
        """Generate markdown report"""
        report = f"""# Derivative Signal Report

**Timestamp:** {signal.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}  
**Symbol:** {signal.symbol}  
**Prediction Window:** {signal.prediction_hours} hours  
**Direction:** **{signal.direction.upper()}**  
**Confidence:** {signal.confidence:.2f}

## Futures Analysis
- **Average Basis:** {features.avg_basis:.4f} ({features.avg_basis*100:.3f}%)
- **Basis Volatility:** {features.basis_volatility:.4f}
- **Basis Momentum:** {features.basis_momentum:.4f}
- **OI Change 24h:** {features.oi_change_24h:.2f}
- **OI Momentum:** {features.oi_momentum:.2f}
- **Volume Ratio:** {features.volume_ratio:.2f}

## Funding Rate Analysis
- **Average Funding Rate:** {features.avg_funding_rate:.6f} ({features.avg_funding_rate*100:.4f}%)
- **Funding Volatility:** {features.funding_rate_volatility:.6f}
- **Funding Momentum:** {features.funding_rate_momentum:.6f}
- **Funding Spread:** {features.funding_rate_spread:.6f}

## Options Analysis
- **Put/Call Ratio:** {features.put_call_ratio:.2f}
- **Implied Volatility:** {features.implied_vol:.2f}
- **Volatility Skew:** {features.vol_skew:.2f}

## Composite Analysis
- **Derivative Sentiment:** {features.derivative_sentiment:.3f}
- **Derivative Confidence:** {features.derivative_confidence:.3f}
- **Market Structure Score:** {features.market_structure_score:.3f}

## Reasoning
{signal.reasoning}

---
*Generated by AlphaCrypto Derivatives v1.0*
"""
        
        with open(self.config.report_file, 'w') as f:
            f.write(report)

# ==============================
# Main Application
# ==============================
class DerivativeApp:
    def __init__(self):
        self.config = DerivativeConfig()
        self._ensure_directories()
        self.collector = DerivativeCollector(self.config)
        self.feature_engine = DerivativeFeatureEngine(self.config)
        self.predictor = DerivativePredictor(self.config)
        self.storage = DerivativeDataStorage(self.config)
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
        print(f"\n🔍 Running Derivative Analysis - {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        
        try:
            # Collect data
            self.collector.collect_data()
            
            # Get recent data for feature calculation
            recent_futures = list(self.collector.futures_buffer)[-10:]
            recent_funding = list(self.collector.funding_buffer)[-10:]
            
            if not recent_futures and not recent_funding:
                print("❌ No derivative data available")
                return
            
            # Calculate features
            latest_futures = recent_futures[-5:] if recent_futures else []
            latest_funding = recent_funding[-5:] if recent_funding else []
            latest_options = list(self.collector.options_buffer)[-5:] if self.collector.options_buffer else []
            
            features = self.feature_engine.calculate_all_features(
                latest_futures, latest_funding, latest_options, recent_futures, recent_funding
            )
            
            # Generate prediction
            signal = self.predictor.generate_prediction(features)
            
            # Save data
            self.storage.save_derivative_data(latest_futures, latest_funding, latest_options)
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
        print(f"🚀 Starting Derivative Data Collection")
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
    
    app = DerivativeApp()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--continuous":
        app.start_continuous_collection()
    else:
        print("Running single derivative analysis...")
        print("Use 'python AlphaCrypto_Derivatives.py --continuous' for continuous collection")
        print("-" * 50)
        app.run_single_analysis()