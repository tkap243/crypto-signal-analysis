# AlphaCrypto Derivatives - Usage Guide

## Overview
This script collects derivative market data to enhance BTC price predictions. It runs independently from your main sentiment+TA and orderbook scripts, collecting high-frequency derivative market structure data.

## Features
- **Futures Data**: Basis (futures-spot spread), open interest, volume
- **Funding Rates**: Cross-exchange funding rate analysis
- **Options Data**: Put/call ratios, implied volatility, skew (placeholder)
- **15-Minute Collection**: Optimized for maximum alpha generation
- **Multi-Exchange Support**: OKX, BitMEX, Deribit (with geographic fallbacks)

## Usage

### Single Analysis
```bash
# Activate virtual environment
source venv/bin/activate

# Run single analysis
python scripts/run_derivatives.py single
```

### Continuous Collection
```bash
# Start continuous data collection every 15 minutes
python scripts/run_derivatives.py continuous
```

### Extended Collection
```bash
# Run for specified duration
python scripts/run_derivatives.py extended --duration 60 --interval 15
```

## Output Files

### Data Files
- `derivative_data.csv` - Raw derivative data (futures, funding, options)
- `derivative_features.csv` - Calculated features over time

### Analysis Files
- `derivative_signals.json` - Latest prediction signal
- `derivative_report.md` - Detailed analysis report

## Key Features Explained

### Futures Analysis
- **Average Basis**: (Futures Price - Spot Price) / Spot Price
- **Basis Volatility**: Standard deviation of basis across exchanges
- **Basis Momentum**: Change in basis over time
- **Open Interest**: Changes in market positioning
- **Volume Ratio**: Current volume vs historical average

### Funding Rate Analysis
- **Average Funding Rate**: Mean funding rate across exchanges
- **Funding Volatility**: Standard deviation of funding rates
- **Funding Momentum**: Change in funding rates over time
- **Funding Spread**: Max - Min funding rates across exchanges

### Options Analysis (Placeholder)
- **Put/Call Ratio**: Sentiment indicator (P/C > 1 = bearish)
- **Implied Volatility**: Market's expectation of volatility
- **Volatility Skew**: Put skew - Call skew

### Composite Features
- **Derivative Sentiment**: Weighted sentiment score (-1 to 1)
- **Derivative Confidence**: Data quality and signal strength
- **Market Structure Score**: Overall derivative market health

## Signal Interpretation

### Direction
- **Bullish**: Positive score > 0.1
- **Bearish**: Negative score < -0.1
- **Neutral**: Score between -0.1 and 0.1

### Confidence
- **High (0.7+)**: Strong signal with clear indicators
- **Medium (0.4-0.7)**: Moderate signal strength
- **Low (0.3-0.4)**: Weak or conflicting signals

## Integration Strategy

### Phase 1: Data Collection
- Run alongside existing orderbook and sentiment+TA scripts
- Collect 2-3 weeks of data for meaningful analysis
- Monitor data quality and exchange availability

### Phase 2: Feature Analysis
- Identify most predictive derivative features
- Compare performance vs existing signals
- Optimize feature weights and thresholds

### Phase 3: Signal Integration
- **Option A**: Three-way fusion (Sentiment + TA + OrderBook + Derivatives)
- **Option B**: Derivative-enhanced confidence adjustment
- **Option C**: Separate derivative signals for specific market conditions

## Performance Expectations

### Realistic Targets
- **Direction Accuracy**: 60-70% (vs 50% random)
- **High Confidence Accuracy**: 75%+
- **Signal Timing**: 30-60 minutes ahead of moves
- **Alpha Generation**: 5-15% improvement over existing signals

### Data Requirements
- **Collection Time**: 2-3 weeks minimum for meaningful analysis
- **Feature Stability**: Monitor feature variance over time
- **Signal Decay**: Derivative signals lose predictive power after 2-4 hours

## Troubleshooting

### Common Issues
1. **Exchange Errors**: Script automatically falls back to working exchanges
2. **Geographic Restrictions**: Some exchanges blocked in certain regions
3. **Data Gaps**: Check internet connection and exchange API status
4. **Feature Calculation**: Ensure sufficient historical data for momentum features

### Monitoring
- Check `derivative_data.csv` for data collection status
- Monitor `derivative_features.csv` for feature stability
- Review `derivative_signals.json` for prediction updates

## Next Steps

1. **Run Continuous Collection**: Start with `continuous` mode
2. **Monitor Performance**: Track prediction accuracy over time
3. **Feature Analysis**: Identify which features are most predictive
4. **Integration Planning**: Consider merging with main scripts if successful

## Timeframe Recommendation

**15-minute collection interval** is optimal because:
- **Futures basis** changes rapidly and is most predictive in 15-30 minute windows
- **Funding rates** update every 8 hours but momentum changes more frequently
- **Options data** is less time-sensitive but still benefits from frequent updates
- **Balances** data freshness with API rate limits and computational efficiency

---
*AlphaCrypto Derivatives v1.0 - Derivative market analysis for enhanced BTC predictions*