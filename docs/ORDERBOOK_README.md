# AlphaCrypto OrderBook - Usage Guide

## Overview
This script analyzes order book and trade data to generate 1-hour BTC price predictions. It runs independently from your main sentiment+TA script and collects high-frequency market microstructure data.

## Features
- **Data Collection**: Order book and trade data every 5 minutes
- **21 Microstructure Features**: Imbalance, spread, trade flow, price impact, momentum
- **1-Hour Predictions**: Optimized for short-term market movements
- **Multi-Exchange Support**: Coinbase, Kraken, Bitfinex (Bybit blocked in some regions)
- **Real-time Analysis**: Updates every 5 minutes

## Usage

### Single Analysis
```bash
# Activate virtual environment
source venv/bin/activate

# Run single analysis
python AlphaCrypto_OrderBook.py
```

### Continuous Collection
```bash
# Start continuous data collection and analysis
python AlphaCrypto_OrderBook.py --continuous
```

## Output Files

### Data Files
- `orderbook_data.csv` - Raw order book snapshots
- `trades_data.csv` - Recent trade data
- `orderbook_features.csv` - Calculated features over time

### Analysis Files
- `orderbook_signals.json` - Latest prediction signal
- `orderbook_report.md` - Detailed analysis report

## Key Features Explained

### Order Book Imbalance
- **Volume Imbalance**: (Bid Volume - Ask Volume) / Total Volume
- **Price Imbalance**: Price-weighted order book imbalance
- **Depth Imbalance**: Number of levels on each side

### Trade Flow Analysis
- **Buy/Sell Pressure**: Volume-weighted trade direction
- **Large Trade Ratio**: Percentage of trades > $10k
- **Trade Frequency**: Trades per minute

### Price Impact
- **0.1% Move Volume**: BTC needed for 0.1% price move
- **0.5% Move Volume**: BTC needed for 0.5% price move
- **Liquidity Concentration**: Volume in top 5 levels

### Momentum Indicators
- **Order Book Momentum**: Change in imbalance over time
- **Trade Momentum**: Change in buy/sell pressure
- **Microstructure Momentum**: Combined momentum signal

## Signal Interpretation

### Direction
- **Bullish**: Positive score > 0.1
- **Bearish**: Negative score < -0.1
- **Neutral**: Score between -0.1 and 0.1

### Confidence
- **High (0.7+)**: Strong signal with clear indicators
- **Medium (0.4-0.7)**: Moderate signal strength
- **Low (0.3-0.4)**: Weak or conflicting signals

## Integration with Main Script

This script runs independently and can be:
1. **Parallel Testing**: Run alongside your 4-hour sentiment+TA script
2. **Data Collection**: Gather order book data for future analysis
3. **Feature Comparison**: Compare order book vs sentiment+TA performance
4. **Future Integration**: Merge signals once performance is validated

## Performance Expectations

### Realistic Targets
- **Direction Accuracy**: 55-65% (vs 50% random)
- **High Confidence Accuracy**: 70%+
- **Signal Timing**: 15-30 minutes ahead of moves

### Data Requirements
- **Collection Time**: 2-3 weeks minimum for meaningful analysis
- **Feature Stability**: Monitor feature variance over time
- **Signal Decay**: Order book signals lose predictive power after 1-2 hours

## Troubleshooting

### Common Issues
1. **Exchange Errors**: Script automatically falls back to working exchanges
2. **Data Gaps**: Check internet connection and exchange API status
3. **Feature Calculation**: Ensure sufficient historical data for momentum features

### Monitoring
- Check `orderbook_data.csv` for data collection status
- Monitor `orderbook_features.csv` for feature stability
- Review `orderbook_signals.json` for prediction updates

## Next Steps

1. **Run Continuous Collection**: Start with `--continuous` mode
2. **Monitor Performance**: Track prediction accuracy over time
3. **Feature Analysis**: Identify which features are most predictive
4. **Integration Planning**: Consider merging with main script if successful

---
*AlphaCrypto OrderBook v1.0 - Independent order book analysis for BTC predictions*