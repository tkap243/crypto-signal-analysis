# AlphaCrypto_OnChain.py
# BTC on-chain data collection and analysis for enhanced predictions
# Collects mempool metrics, fee estimates, and network stats every 15 minutes
# Generates 1-hour directional signals using on-chain market structure

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
import requests
from pathlib import Path

# ==============================
# Configuration
# ==============================
@dataclass
class OnChainConfig:
    symbol: str = "BTC/USDT"
    prediction_hours: float = 1.0  # 1-hour predictions
    data_collection_interval: int = 900  # 15 minutes (900 seconds)
    feature_window_minutes: int = 60  # 1-hour rolling windows
    signal_update_minutes: int = 15  # Update signals every 15 minutes
    max_data_points: int = 96  # 24 hours of 15-minute data
    
    # API endpoints
    mempool_base: str = "https://mempool.space/api"
    blockchair_base: str = "https://api.blockchair.com/bitcoin"
    
    # Output files
    onchain_data_file: str = "data/raw/onchain_data.csv"
    features_file: str = "data/processed/onchain_features.csv"
    signals_file: str = "data/outputs/onchain_signals.json"
    report_file: str = "data/outputs/reports/onchain_report.md"
    
    # Feature calculation parameters
    mempool_congestion_threshold: float = 50000  # High mempool count threshold
    fee_pressure_threshold: float = 50  # High fee threshold (sat/vB)
    network_activity_threshold: float = 0.1  # 10% change in network activity

@dataclass
class OnChainData:
    timestamp: datetime
    symbol: str
    
    # Mempool metrics
    mempool_count: Optional[int] = None
    mempool_vsize: Optional[int] = None
    mempool_total_fee_btc: Optional[float] = None
    
    # Fee estimates
    fee_fastest_satvB: Optional[float] = None
    fee_30min_satvB: Optional[float] = None
    fee_60min_satvB: Optional[float] = None
    fee_economy_satvB: Optional[float] = None
    fee_min_satvB: Optional[float] = None
    
    # Latest block info
    tip_height: Optional[int] = None
    tip_timestamp: Optional[int] = None
    tip_tx_count: Optional[int] = None
    tip_size: Optional[int] = None
    tip_weight: Optional[int] = None
    
    # Blockchair network stats
    bc_blocks: Optional[int] = None
    bc_transactions: Optional[int] = None
    bc_mempool_transactions: Optional[int] = None
    bc_circulation: Optional[float] = None
    bc_market_price_usd: Optional[float] = None
    bc_hashrate_24h: Optional[float] = None
    bc_difficulty: Optional[float] = None
    bc_average_transaction_fee_24h_usd: Optional[float] = None
    bc_average_transaction_value_24h_usd: Optional[float] = None
    bc_median_transaction_fee_24h_usd: Optional[float] = None
    
    # Latest block summary
    bc_tip_id: Optional[str] = None
    bc_tip_time: Optional[str] = None
    bc_tip_tx_count: Optional[int] = None
    bc_tip_size: Optional[int] = None
    bc_tip_weight: Optional[int] = None
    bc_tip_difficulty: Optional[float] = None

@dataclass
class OnChainFeatures:
    timestamp: datetime
    symbol: str
    
    # Mempool congestion features
    mempool_congestion_score: float = 0.0
    mempool_trend: float = 0.0
    mempool_volatility: float = 0.0
    
    # Fee pressure features
    fee_pressure_score: float = 0.0
    fee_trend: float = 0.0
    fee_volatility: float = 0.0
    
    # Network activity features
    network_activity_score: float = 0.0
    network_trend: float = 0.0
    network_volatility: float = 0.0
    
    # Block production features
    block_production_rate: float = 0.0
    block_size_trend: float = 0.0
    block_weight_trend: float = 0.0
    
    # Market structure features
    market_structure_score: float = 0.0
    liquidity_score: float = 0.0
    volatility_score: float = 0.0

@dataclass
class OnChainSignal:
    timestamp: datetime
    symbol: str
    signal_type: str
    signal_strength: float
    confidence: float
    reasoning: str
    features_used: List[str]
    prediction_hours: float

class OnChainApp:
    def __init__(self, config: OnChainConfig = None):
        self.config = config or OnChainConfig()
        self.data_buffer = deque(maxlen=self.config.max_data_points)
        self.features_buffer = deque(maxlen=self.config.max_data_points)
        self.signals_buffer = deque(maxlen=24)  # Keep 24 hours of signals
        
        # Ensure output directories exist
        self._ensure_directories()
        
        # Load existing data
        self._load_existing_data()
        
    def _ensure_directories(self):
        """Ensure all output directories exist"""
        directories = [
            "data/raw",
            "data/processed", 
            "data/outputs",
            "data/outputs/reports"
        ]
        for directory in directories:
            Path(directory).mkdir(parents=True, exist_ok=True)
    
    def _load_existing_data(self):
        """Load existing data from CSV files"""
        try:
            # Check if running in GitHub Actions
            is_github_actions = os.getenv('GITHUB_ACTIONS') == 'true'
            
            # Load raw data
            if os.path.exists(self.config.onchain_data_file):
                df = pd.read_csv(self.config.onchain_data_file)
                df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')
                
                if is_github_actions:
                    print(f"🔄 GitHub Actions detected - loading all historical data for feature calculations")
                
                for _, row in df.iterrows():
                    data = OnChainData(**{k: v for k, v in row.items() if k in OnChainData.__dataclass_fields__})
                    self.data_buffer.append(data)
                print(f"📊 Loaded {len(self.data_buffer)} existing onchain data points")
            
            # Load features
            if os.path.exists(self.config.features_file):
                df = pd.read_csv(self.config.features_file)
                df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')
                
                if is_github_actions:
                    print(f"🔄 GitHub Actions detected - loading all historical features")
                
                for _, row in df.iterrows():
                    features = OnChainFeatures(**{k: v for k, v in row.items() if k in OnChainFeatures.__dataclass_fields__})
                    self.features_buffer.append(features)
                print(f"🔍 Loaded {len(self.features_buffer)} existing feature points")
                
        except Exception as e:
            print(f"⚠️  Warning: Could not load existing data: {e}")
    
    def _safe_get(self, url: str, timeout: int = 15) -> Dict[str, Any]:
        """Safely fetch data from API with error handling"""
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"_error": str(e), "_source": url}
    
    def _get_mempool_metrics(self) -> Dict[str, Any]:
        """Fetch mempool metrics from mempool.space"""
        # Mempool data
        mempool = self._safe_get(f"{self.config.mempool_base}/mempool")
        # Fee recommendations
        fees = self._safe_get(f"{self.config.mempool_base}/v1/fees/recommended")
        # Recent blocks
        blocks = self._safe_get(f"{self.config.mempool_base}/blocks")
        latest_block = blocks[0] if isinstance(blocks, list) and blocks else {}
        
        return {
            "mempool_count": mempool.get("count"),
            "mempool_vsize": mempool.get("vsize"),
            "mempool_total_fee_btc": mempool.get("total_fee"),
            "fee_fastest_satvB": fees.get("fastestFee"),
            "fee_30min_satvB": fees.get("halfHourFee"),
            "fee_60min_satvB": fees.get("hourFee"),
            "fee_economy_satvB": fees.get("economyFee"),
            "fee_min_satvB": fees.get("minimumFee"),
            "tip_height": latest_block.get("height"),
            "tip_timestamp": latest_block.get("timestamp"),
            "tip_tx_count": latest_block.get("tx_count"),
            "tip_size": latest_block.get("size"),
            "tip_weight": latest_block.get("weight"),
        }
    
    def _get_blockchair_stats(self) -> Dict[str, Any]:
        """Fetch network stats from Blockchair"""
        # Network statistics
        stats = self._safe_get(f"{self.config.blockchair_base}/stats")
        data = stats.get("data", {}) if isinstance(stats, dict) else {}
        
        # Latest block
        latest_blocks = self._safe_get(f"{self.config.blockchair_base}/blocks?limit=1")
        latest_data = latest_blocks.get("data", []) if isinstance(latest_blocks, dict) else []
        latest = latest_data[0] if latest_data else {}
        
        return {
            "bc_blocks": data.get("blocks"),
            "bc_transactions": data.get("transactions"),
            "bc_mempool_transactions": data.get("mempool_transactions"),
            "bc_circulation": data.get("circulation"),
            "bc_market_price_usd": data.get("market_price_usd"),
            "bc_hashrate_24h": data.get("hashrate_24h"),
            "bc_difficulty": data.get("difficulty"),
            "bc_average_transaction_fee_24h_usd": data.get("average_transaction_fee_24h_usd"),
            "bc_average_transaction_value_24h_usd": data.get("average_transaction_value_24h_usd"),
            "bc_median_transaction_fee_24h_usd": data.get("median_transaction_fee_24h_usd"),
            "bc_tip_id": latest.get("id"),
            "bc_tip_time": latest.get("time"),
            "bc_tip_tx_count": latest.get("transaction_count") or latest.get("transaction_count_approx"),
            "bc_tip_size": latest.get("size"),
            "bc_tip_weight": latest.get("weight"),
            "bc_tip_difficulty": latest.get("difficulty"),
        }
    
    def collect_data(self) -> OnChainData:
        """Collect onchain data from APIs"""
        timestamp = datetime.now(timezone.utc)
        
        # Fetch data from both sources
        mempool_data = self._get_mempool_metrics()
        blockchair_data = self._get_blockchair_stats()
        
        # Combine data
        data_dict = {
            "timestamp": timestamp,
            "symbol": self.config.symbol,
            **mempool_data,
            **blockchair_data
        }
        
        # Create OnChainData object
        onchain_data = OnChainData(**data_dict)
        
        # Add to buffer
        self.data_buffer.append(onchain_data)
        
        return onchain_data
    
    def calculate_features(self, data: OnChainData) -> OnChainFeatures:
        """Calculate features from onchain data"""
        timestamp = data.timestamp
        
        try:
            # Convert buffer to DataFrame for calculations
            if len(self.data_buffer) < 1:
                print("⚠️  No data in buffer for feature calculation")
                return OnChainFeatures(timestamp=timestamp, symbol=data.symbol)
            
            df = pd.DataFrame([asdict(d) for d in self.data_buffer])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
            
            # Mempool congestion features
            mempool_congestion_score = self._calculate_congestion_score(data)
            mempool_trend = self._calculate_trend(df, 'mempool_count') if len(df) >= 2 else 0.0
            mempool_volatility = self._calculate_volatility(df, 'mempool_count') if len(df) >= 2 else 0.0
            
            # Fee pressure features
            fee_pressure_score = self._calculate_fee_pressure_score(data)
            fee_trend = self._calculate_trend(df, 'fee_30min_satvB') if len(df) >= 2 else 0.0
            fee_volatility = self._calculate_volatility(df, 'fee_30min_satvB') if len(df) >= 2 else 0.0
            
            # Network activity features
            network_activity_score = self._calculate_network_activity_score(data)
            network_trend = self._calculate_trend(df, 'bc_transactions') if len(df) >= 2 else 0.0
            network_volatility = self._calculate_volatility(df, 'bc_transactions') if len(df) >= 2 else 0.0
            
            # Block production features
            block_production_rate = self._calculate_block_production_rate(df) if len(df) >= 2 else 0.0
            block_size_trend = self._calculate_trend(df, 'tip_size') if len(df) >= 2 else 0.0
            block_weight_trend = self._calculate_trend(df, 'tip_weight') if len(df) >= 2 else 0.0
            
            # Market structure features
            market_structure_score = self._calculate_market_structure_score(data)
            liquidity_score = self._calculate_liquidity_score(data)
            volatility_score = self._calculate_volatility_score(df) if len(df) >= 2 else 0.0
            
            features = OnChainFeatures(
                timestamp=timestamp,
                symbol=data.symbol,
                mempool_congestion_score=mempool_congestion_score,
                mempool_trend=mempool_trend,
                mempool_volatility=mempool_volatility,
                fee_pressure_score=fee_pressure_score,
                fee_trend=fee_trend,
                fee_volatility=fee_volatility,
                network_activity_score=network_activity_score,
                network_trend=network_trend,
                network_volatility=network_volatility,
                block_production_rate=block_production_rate,
                block_size_trend=block_size_trend,
                block_weight_trend=block_weight_trend,
                market_structure_score=market_structure_score,
                liquidity_score=liquidity_score,
                volatility_score=volatility_score
            )
            
            self.features_buffer.append(features)
            print(f"🔍 Calculated features for {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            return features
            
        except Exception as e:
            print(f"❌ Error calculating features: {e}")
            # Return basic features even if calculation fails
            return OnChainFeatures(timestamp=timestamp, symbol=data.symbol)
    
    def _calculate_congestion_score(self, data: OnChainData) -> float:
        """Calculate mempool congestion score (0-1)"""
        if data.mempool_count is None:
            return 0.0
        
        # Normalize based on typical ranges
        if data.mempool_count < 1000:
            return 0.0
        elif data.mempool_count < 10000:
            return (data.mempool_count - 1000) / 9000
        elif data.mempool_count < 50000:
            return 0.5 + (data.mempool_count - 10000) / 80000
        else:
            return min(1.0, 0.5 + (data.mempool_count - 50000) / 100000)
    
    def _calculate_fee_pressure_score(self, data: OnChainData) -> float:
        """Calculate fee pressure score (0-1)"""
        if data.fee_30min_satvB is None:
            return 0.0
        
        # Normalize based on typical fee ranges
        if data.fee_30min_satvB < 1:
            return 0.0
        elif data.fee_30min_satvB < 10:
            return data.fee_30min_satvB / 10
        elif data.fee_30min_satvB < 50:
            return 0.5 + (data.fee_30min_satvB - 10) / 80
        else:
            return min(1.0, 0.5 + (data.fee_30min_satvB - 50) / 100)
    
    def _calculate_network_activity_score(self, data: OnChainData) -> float:
        """Calculate network activity score (0-1)"""
        if data.bc_transactions is None:
            return 0.0
        
        # Normalize based on typical daily transaction counts
        daily_tx = data.bc_transactions / 144  # Approximate 10-minute blocks
        if daily_tx < 200000:
            return daily_tx / 200000
        elif daily_tx < 400000:
            return 0.5 + (daily_tx - 200000) / 400000
        else:
            return min(1.0, 0.5 + (daily_tx - 400000) / 200000)
    
    def _calculate_trend(self, df: pd.DataFrame, column: str) -> float:
        """Calculate trend for a column (slope of linear regression)"""
        if len(df) < 2 or column not in df.columns:
            return 0.0
        
        valid_data = df[column].dropna()
        if len(valid_data) < 2:
            return 0.0
        
        x = np.arange(len(valid_data))
        y = valid_data.values
        slope = np.polyfit(x, y, 1)[0]
        return float(slope)
    
    def _calculate_volatility(self, df: pd.DataFrame, column: str) -> float:
        """Calculate volatility (standard deviation) for a column"""
        if len(df) < 2 or column not in df.columns:
            return 0.0
        
        valid_data = df[column].dropna()
        if len(valid_data) < 2:
            return 0.0
        
        return float(valid_data.std())
    
    def _calculate_block_production_rate(self, df: pd.DataFrame) -> float:
        """Calculate average block production rate"""
        if len(df) < 2:
            return 0.0
        
        # Calculate time between blocks
        timestamps = pd.to_datetime(df['timestamp'])
        time_diffs = timestamps.diff().dt.total_seconds()
        avg_block_time = time_diffs.mean()
        
        if pd.isna(avg_block_time) or avg_block_time == 0:
            return 0.0
        
        # Convert to blocks per hour
        return 3600 / avg_block_time
    
    def _calculate_market_structure_score(self, data: OnChainData) -> float:
        """Calculate overall market structure score"""
        congestion = self._calculate_congestion_score(data)
        fee_pressure = self._calculate_fee_pressure_score(data)
        activity = self._calculate_network_activity_score(data)
        
        # Weighted combination
        return (congestion * 0.4 + fee_pressure * 0.3 + activity * 0.3)
    
    def _calculate_liquidity_score(self, data: OnChainData) -> float:
        """Calculate liquidity score based on transaction volume and fees"""
        if data.bc_average_transaction_value_24h_usd is None or data.fee_30min_satvB is None:
            return 0.0
        
        # Higher transaction values and lower fees indicate better liquidity
        value_score = min(1.0, data.bc_average_transaction_value_24h_usd / 1000000)  # Normalize to $1M
        fee_score = max(0.0, 1.0 - (data.fee_30min_satvB / 100))  # Lower fees = higher liquidity
        
        return (value_score + fee_score) / 2
    
    def _calculate_volatility_score(self, df: pd.DataFrame) -> float:
        """Calculate overall volatility score"""
        if len(df) < 2:
            return 0.0
        
        # Calculate volatility for key metrics
        mempool_vol = self._calculate_volatility(df, 'mempool_count')
        fee_vol = self._calculate_volatility(df, 'fee_30min_satvB')
        tx_vol = self._calculate_volatility(df, 'bc_transactions')
        
        # Normalize and combine
        return (mempool_vol / 10000 + fee_vol / 50 + tx_vol / 100000) / 3
    
    def generate_signal(self, features: OnChainFeatures) -> OnChainSignal:
        """Generate trading signal based on features"""
        timestamp = features.timestamp
        
        # Signal logic based on onchain metrics
        signal_strength = 0.0
        confidence = 0.0
        reasoning_parts = []
        features_used = []
        
        # Mempool congestion signal
        if features.mempool_congestion_score > 0.7:
            signal_strength += 0.3
            confidence += 0.2
            reasoning_parts.append("High mempool congestion")
            features_used.append("mempool_congestion_score")
        elif features.mempool_congestion_score < 0.3:
            signal_strength -= 0.2
            confidence += 0.1
            reasoning_parts.append("Low mempool congestion")
            features_used.append("mempool_congestion_score")
        
        # Fee pressure signal
        if features.fee_pressure_score > 0.7:
            signal_strength += 0.2
            confidence += 0.2
            reasoning_parts.append("High fee pressure")
            features_used.append("fee_pressure_score")
        elif features.fee_pressure_score < 0.3:
            signal_strength -= 0.1
            confidence += 0.1
            reasoning_parts.append("Low fee pressure")
            features_used.append("fee_pressure_score")
        
        # Network activity signal
        if features.network_activity_score > 0.7:
            signal_strength += 0.2
            confidence += 0.2
            reasoning_parts.append("High network activity")
            features_used.append("network_activity_score")
        elif features.network_activity_score < 0.3:
            signal_strength -= 0.1
            confidence += 0.1
            reasoning_parts.append("Low network activity")
            features_used.append("network_activity_score")
        
        # Market structure signal
        if features.market_structure_score > 0.7:
            signal_strength += 0.3
            confidence += 0.2
            reasoning_parts.append("Strong market structure")
            features_used.append("market_structure_score")
        elif features.market_structure_score < 0.3:
            signal_strength -= 0.2
            confidence += 0.1
            reasoning_parts.append("Weak market structure")
            features_used.append("market_structure_score")
        
        # Normalize signal strength to [-1, 1]
        signal_strength = max(-1.0, min(1.0, signal_strength))
        confidence = max(0.0, min(1.0, confidence))
        
        # Determine signal type
        if signal_strength > 0.3:
            signal_type = "BULLISH"
        elif signal_strength < -0.3:
            signal_type = "BEARISH"
        else:
            signal_type = "NEUTRAL"
        
        reasoning = "; ".join(reasoning_parts) if reasoning_parts else "Insufficient data"
        
        signal = OnChainSignal(
            timestamp=timestamp,
            symbol=features.symbol,
            signal_type=signal_type,
            signal_strength=signal_strength,
            confidence=confidence,
            reasoning=reasoning,
            features_used=features_used,
            prediction_hours=self.config.prediction_hours
        )
        
        self.signals_buffer.append(signal)
        return signal
    
    def save_data(self):
        """Save all data to CSV files"""
        try:
            # Save raw data - append new data points
            if self.data_buffer:
                # Get only new data points (not already saved)
                new_data_points = []
                for data in self.data_buffer:
                    data_dict = asdict(data)
                    data_dict['timestamp'] = data.timestamp.isoformat()
                    new_data_points.append(data_dict)
                
                # Append to CSV file
                df = pd.DataFrame(new_data_points)
                file_exists = os.path.exists(self.config.onchain_data_file)
                df.to_csv(self.config.onchain_data_file, mode='a', header=not file_exists, index=False)
                print(f"💾 Saved {len(new_data_points)} new onchain data points")
            
            # Save features - append new feature points
            if self.features_buffer:
                # Get only new feature points (not already saved)
                new_features_points = []
                for features in self.features_buffer:
                    features_dict = asdict(features)
                    features_dict['timestamp'] = features.timestamp.isoformat()
                    new_features_points.append(features_dict)
                
                # Append to CSV file
                df = pd.DataFrame(new_features_points)
                file_exists = os.path.exists(self.config.features_file)
                df.to_csv(self.config.features_file, mode='a', header=not file_exists, index=False)
                print(f"🔍 Saved {len(new_features_points)} new feature points")
            
            # Save signals - overwrite the entire signals file (keep latest signals)
            if self.signals_buffer:
                signals_data = [asdict(signal) for signal in self.signals_buffer]
                # Convert timestamps to ISO format
                for signal in signals_data:
                    if 'timestamp' in signal:
                        signal['timestamp'] = signal['timestamp'].isoformat()
                
                with open(self.config.signals_file, 'w') as f:
                    json.dump(signals_data, f, indent=2, default=str)
                print(f"📊 Saved {len(self.signals_buffer)} signals")
                
        except Exception as e:
            print(f"❌ Error saving data: {e}")
            raise
    
    def generate_report(self):
        """Generate analysis report"""
        try:
            if not self.data_buffer:
                print("⚠️  No data available for report generation")
                return
            
            # Convert to DataFrames
            data_df = pd.DataFrame([asdict(data) for data in self.data_buffer])
            data_df['timestamp'] = pd.to_datetime(data_df['timestamp'])
            
            features_df = pd.DataFrame([asdict(features) for features in self.features_buffer]) if self.features_buffer else pd.DataFrame()
            if not features_df.empty:
                features_df['timestamp'] = pd.to_datetime(features_df['timestamp'])
            
            # Generate report
            # Calculate metrics safely
            avg_mempool = f"{data_df['mempool_count'].mean():.0f}" if not data_df['mempool_count'].isna().all() else 'N/A'
            avg_fee = f"{data_df['fee_30min_satvB'].mean():.1f}" if not data_df['fee_30min_satvB'].isna().all() else 'N/A'
            avg_network = f"{features_df['network_activity_score'].mean():.3f}" if not features_df.empty and not features_df['network_activity_score'].isna().all() else 'N/A'
            avg_market = f"{features_df['market_structure_score'].mean():.3f}" if not features_df.empty and not features_df['market_structure_score'].isna().all() else 'N/A'
            
            report = f"""# OnChain Analysis Report
Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

## Data Summary
- **Data Points**: {len(self.data_buffer)}
- **Feature Points**: {len(self.features_buffer)}
- **Signals Generated**: {len(self.signals_buffer)}
- **Time Range**: {data_df['timestamp'].min()} to {data_df['timestamp'].max()}

## Key Metrics
- **Avg Mempool Count**: {avg_mempool}
- **Avg Fee (30min)**: {avg_fee} sat/vB
- **Avg Network Activity**: {avg_network}
- **Avg Market Structure**: {avg_market}

## Recent Signals
"""
            
            # Add recent signals
            if self.signals_buffer:
                for signal in list(self.signals_buffer)[-5:]:
                    report += f"- **{signal.signal_type}** ({signal.signal_strength:.2f}) - {signal.reasoning}\n"
            else:
                report += "- No signals generated yet\n"
            
            # Save report
            with open(self.config.report_file, 'w') as f:
                f.write(report)
            
            print(f"📄 Report saved to {self.config.report_file}")
            
        except Exception as e:
            print(f"❌ Error generating report: {e}")
            # Create a minimal report even if generation fails
            try:
                minimal_report = f"""# OnChain Analysis Report
Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

## Data Summary
- **Data Points**: {len(self.data_buffer) if self.data_buffer else 0}
- **Feature Points**: {len(self.features_buffer) if self.features_buffer else 0}
- **Signals Generated**: {len(self.signals_buffer) if self.signals_buffer else 0}

## Status
Report generation encountered an error: {e}
"""
                with open(self.config.report_file, 'w') as f:
                    f.write(minimal_report)
                print(f"📄 Minimal report saved to {self.config.report_file}")
            except Exception as e2:
                print(f"❌ Failed to save minimal report: {e2}")
    
    def run_single_analysis(self):
        """Run single onchain analysis"""
        print("🔍 Running single onchain analysis...")
        
        try:
            # Collect data
            data = self.collect_data()
            print(f"📊 Collected data: mempool={data.mempool_count}, fee={data.fee_30min_satvB} sat/vB")
            
            # Calculate features
            features = self.calculate_features(data)
            print(f"🔍 Calculated features: congestion={features.mempool_congestion_score:.3f}, pressure={features.fee_pressure_score:.3f}")
            
            # Generate signal
            signal = self.generate_signal(features)
            print(f"📊 Generated signal: {signal.signal_type} ({signal.signal_strength:.2f}) - {signal.reasoning}")
            
            # Save data
            self.save_data()
            
            # Generate report
            self.generate_report()
            
            print("✅ Single onchain analysis completed")
            
        except Exception as e:
            print(f"❌ Error in onchain analysis: {e}")
            # Try to save whatever data we have
            try:
                self.save_data()
                self.generate_report()
                print("💾 Saved partial data despite error")
            except Exception as save_error:
                print(f"❌ Failed to save partial data: {save_error}")
            raise
    
    def start_continuous_collection(self):
        """Start continuous data collection"""
        print("🔄 Starting continuous onchain collection...")
        print("Press Ctrl+C to stop")
        
        def collect_loop():
            while True:
                try:
                    self.run_single_analysis()
                    time.sleep(self.config.data_collection_interval)
                except KeyboardInterrupt:
                    print("\n🛑 Collection stopped by user")
                    break
                except Exception as e:
                    print(f"❌ Collection error: {e}")
                    time.sleep(60)  # Wait 1 minute before retry
        
        # Run in separate thread
        thread = threading.Thread(target=collect_loop)
        thread.daemon = True
        thread.start()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Stopping collection...")
            self.save_data()
            self.generate_report()
            print("✅ Collection stopped and data saved")