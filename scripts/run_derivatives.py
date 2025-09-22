#!/usr/bin/env python3
"""
Derivative Data Collection Management Script

This script collects derivative market data to enhance BTC price predictions:
- Futures data (basis, open interest, volume)
- Funding rates across exchanges
- Options data (put/call ratios, implied volatility)
- Perpetual swap metrics

Usage:
    python scripts/run_derivatives.py [mode] [options]
    
Modes:
    single      - Run single collection (default)
    continuous  - Run continuous collection every 15 minutes
    extended    - Run for specified duration
    
Examples:
    python scripts/run_derivatives.py single
    python scripts/run_derivatives.py continuous
    python scripts/run_derivatives.py extended --duration 60 --interval 15
"""

import sys
import os
import argparse
import time
from datetime import datetime, timedelta, timezone

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from AlphaCrypto_Derivatives import DerivativeApp

def run_single():
    """Run single derivative analysis"""
    print("🔍 Running single derivative analysis...")
    app = DerivativeApp()
    app.run_single_analysis()
    print("✅ Single analysis completed")

def run_continuous():
    """Run continuous derivative collection"""
    print("🔄 Starting continuous derivative collection...")
    print("Press Ctrl+C to stop")
    
    app = DerivativeApp()
    app.start_continuous_collection()

def run_extended(duration_minutes, interval_seconds):
    """Run extended collection for specified duration"""
    print(f"⏱️  Starting extended collection: {duration_minutes} minutes, {interval_seconds}s intervals")
    
    app = DerivativeApp()
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
    parser = argparse.ArgumentParser(description='Derivative Data Collection Management')
    parser.add_argument('mode', nargs='?', default='single', 
                       choices=['single', 'continuous', 'extended'],
                       help='Collection mode (default: single)')
    parser.add_argument('--duration', type=int, default=60,
                       help='Duration in minutes for extended mode (default: 60)')
    parser.add_argument('--interval', type=int, default=15,
                       help='Collection interval in seconds (default: 15)')
    
    args = parser.parse_args()
    
    print(f"🚀 Derivative Data Collection Manager")
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