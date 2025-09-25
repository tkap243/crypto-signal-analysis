# AlphaCrypto OnChain - Usage Guide

## Overview
This script collects on-chain data to enhance BTC price predictions. It runs independently from your main sentiment+TA, orderbook, and derivatives scripts, collecting blockchain metrics and network statistics.

## Features
- **Mempool Metrics**: Transaction count, size, total fees
- **Fee Estimates**: Real-time fee recommendations across timeframes
- **Network Statistics**: Hashrate, difficulty, transaction volume
- **Block Production**: Block size, weight, and production rate analysis
- **15-Minute Collection**: Optimized for market structure analysis
- **Dual-Source Validation**: Mempool.space + Blockchair for data reliability

## Usage

### Single Analysis
```bash
# Activate virtual environment
source venv/bin/activate

# Run single analysis
python scripts/run_onchain.py single
```

### Continuous Collection
```bash
# Start continuous data collection every 15 minutes
python scripts/run_onchain.py continuous
```

### Extended Collection
```bash
# Run for specified duration
python scripts/run_onchain.py extended --duration 60 --interval 15
```

## Output Files

### Data Files
- `onchain_data.csv` - Raw on-chain data (mempool, fees, network stats)
- `onchain_features.csv` - Calculated features over time

### Analysis Files
- `onchain_signals.json` - Latest prediction signal
- `onchain_report.md` - Detailed analysis report

## Key Features Explained

### Mempool Analysis
- **Congestion Score**: Normalized mempool transaction count (0-1)
- **Mempool Trend**: Rate of change in mempool size
- **Mempool Volatility**: Standard deviation of mempool metrics

### Fee Pressure Analysis
- **Fee Pressure Score**: Normalized fee levels across timeframes (0-1)
- **Fee Trend**: Rate of change in fee recommendations
- **Fee Volatility**: Standard deviation of fee estimates

### Network Activity Analysis
- **Activity Score**: Normalized transaction volume (0-1)
- **Network Trend**: Rate of change in network activity
- **Network Volatility**: Standard deviation of network metrics

### Block Production Analysis
- **Production Rate**: Average blocks per hour
- **Block Size Trend**: Rate of change in block sizes
- **Block Weight Trend**: Rate of change in block weights

## Signal Generation

The system generates trading signals based on:

### Bullish Signals
- High mempool congestion (>0.7) - indicates demand
- High fee pressure (>0.7) - indicates urgency
- High network activity (>0.7) - indicates usage
- Strong market structure (>0.7) - indicates stability

### Bearish Signals
- Low mempool congestion (<0.3) - indicates low demand
- Low fee pressure (<0.3) - indicates low urgency
- Low network activity (<0.3) - indicates low usage
- Weak market structure (<0.3) - indicates instability

### Signal Strength
- **Range**: -1.0 (strong bearish) to +1.0 (strong bullish)
- **Confidence**: 0.0 to 1.0 based on data quality and consistency
- **Features Used**: List of contributing factors

## Data Sources

### Mempool.space
- **Mempool Data**: Real-time mempool metrics
- **Fee Recommendations**: Fastest, 30min, 60min, economy, minimum
- **Block Data**: Recent block information

### Blockchair
- **Network Statistics**: Hashrate, difficulty, transaction counts
- **Market Data**: Price, circulation, fee statistics
- **Block Information**: Latest block details

## Configuration

### Default Settings
- **Collection Interval**: 15 minutes
- **Feature Window**: 60 minutes
- **Signal Update**: Every 15 minutes
- **Max Data Points**: 96 (24 hours)

### Customization
Modify `OnChainConfig` in `src/AlphaCrypto_OnChain.py`:
```python
@dataclass
class OnChainConfig:
    data_collection_interval: int = 900  # 15 minutes
    feature_window_minutes: int = 60     # 1 hour
    signal_update_minutes: int = 15      # 15 minutes
    # ... other parameters
```

## Error Handling

The system includes robust error handling:
- **API Timeouts**: 15-second timeout with graceful fallback
- **Data Validation**: Checks for missing or invalid data
- **Retry Logic**: Automatic retry on collection errors
- **Graceful Degradation**: Continues operation with partial data

## Monitoring

### Log Messages
- `📊 Collected data`: Data collection confirmation
- `🔍 Calculated features`: Feature calculation status
- `📊 Generated signal`: Signal generation result
- `💾 Saved data`: Data persistence confirmation
- `📄 Report saved`: Report generation confirmation

### Error Messages
- `⚠️ Warning`: Non-critical issues
- `❌ Error`: Collection or processing errors
- `🛑 Stopped`: User interruption or system stop

## Integration

This module integrates with your existing AlphaCrypto system:
- **Independent Operation**: Runs separately from other modules
- **Consistent Architecture**: Matches project structure and patterns
- **Shared Data Format**: Compatible with existing analysis tools
- **Unified Reporting**: Follows project documentation standards

## Troubleshooting

### Common Issues
1. **API Rate Limits**: System includes built-in delays and retry logic
2. **Network Connectivity**: Check internet connection and firewall settings
3. **Data Quality**: Some metrics may be missing during network issues
4. **File Permissions**: Ensure write access to data directories

### Debug Mode
Enable verbose logging by modifying the print statements in the code or adding logging configuration.

## Future Enhancements

Planned improvements:
- **Additional Metrics**: Lightning network data, mining pool analysis
- **Advanced Features**: Cross-chain analysis, DeFi metrics
- **Machine Learning**: Enhanced signal generation with ML models
- **Real-time Alerts**: Notification system for significant signals