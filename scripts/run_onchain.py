#!/usr/bin/env python3
"""
OnChain Data Collection Management Script

This script collects on-chain data to enhance BTC price predictions:
- Mempool metrics (count, size, fees)
- Network statistics (hashrate, difficulty, transactions)
- Fee estimates across different timeframes
- Block production metrics

Usage:
    python scripts/run_onchain.py [mode] [options]
    
Modes:
    single      - Run single collection (default)
    continuous  - Run continuous collection every 15 minutes
    extended    - Run for specified duration
    
Examples:
    python scripts/run_onchain.py single
    python scripts/run_onchain.py continuous
    python scripts/run_onchain.py extended --duration 60 --interval 15
"""

import sys
import os
import argparse
import time
from datetime import datetime, timedelta, timezone

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from AlphaCrypto_OnChain import OnChainApp

def run_single():
    """Run single onchain analysis"""
    print("🔍 Running single onchain analysis...")
    app = OnChainApp()
    app.run_single_analysis()
    print("✅ Single analysis completed")

def run_continuous():
    """Run continuous onchain collection"""
    print("🔄 Starting continuous onchain collection...")
    print("Press Ctrl+C to stop")
    
    app = OnChainApp()
    app.start_continuous_collection()

def run_extended(duration_minutes, interval_seconds):
    """Run extended collection for specified duration"""
    print(f"⏱️  Starting extended collection: {duration_minutes} minutes, {interval_seconds}s intervals")
    
    app = OnChainApp()
    end_time = time.time() + (duration_minutes * 60)
    collection_count = 0
    
    try:
        while time.time() < end_time:
            try:
                app.run_single_analysis()
                collection_count += 1
                remaining_time = int((end_time - time.time()) / 60)
                print(f"Collection #{collection_count} completed. {remaining_time} minutes remaining")
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                print("\n🛑 Collection stopped by user")
                break
            except Exception as e:
                print(f"❌ Collection error: {e}")
                time.sleep(5)
                
        print(f"✅ Extended collection completed: {collection_count} data points collected")
        
    except KeyboardInterrupt:
        print(f"\n🛑 Collection stopped: {collection_count} data points collected")

def main():
    parser = argparse.ArgumentParser(description='OnChain Data Collection Management')
    parser.add_argument('mode', nargs='?', default='single', 
                       choices=['single', 'continuous', 'extended'],
                       help='Collection mode (default: single)')
    parser.add_argument('--duration', type=int, default=60,
                       help='Duration in minutes for extended mode (default: 60)')
    parser.add_argument('--interval', type=int, default=15,
                       help='Collection interval in seconds (default: 15)')
    
    args = parser.parse_args()
    
    print(f"🚀 OnChain Data Collection Manager")
    print(f"Mode: {args.mode}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 50)
    
    if args.mode == 'single':
        run_single()
    elif args.mode == 'continuous':
        run_continuous()
    elif args.mode == 'extended':
        run_extended(args.duration, args.interval)

if __name__ == "__main__":
    main()