# AlpabrosCrypto - BTC Prediction System

A comprehensive Bitcoin price prediction system using sentiment analysis, technical analysis, and order book microstructure data.

## 🏗️ Project Structure

```
AlpabrosCrypto/
├── 📄 AlphaCrypto.py              # Main sentiment+TA script (production)
├── 📁 src/                        # Source code
│   └── 📄 AlphaCrypto_OrderBook.py # Order book analysis script
├── 📁 data/                       # Data storage
│   ├── 📁 raw/                    # Raw collected data
│   │   ├── 📄 orderbook_data.csv
│   │   └── 📄 trades_data.csv
│   ├── 📁 processed/              # Processed features
│   │   ├── 📄 features.csv
│   │   └── 📄 orderbook_features.csv
│   ├── 📁 outputs/                # Analysis outputs
│   │   ├── 📄 signal.json
│   │   ├── 📄 orderbook_signals.json
│   │   ├── 📁 reports/
│   │   │   ├── 📄 report.md
│   │   │   └── 📄 orderbook_report.md
│   │   └── 📁 logs/
│   │       ├── 📄 audit.log
│   │       └── 📄 last_run.txt
│   └── 📁 archive/                # Archived data
├── 📁 notebooks/                  # Jupyter notebooks
│   ├── 📄 EDAOrderbook.ipynb
│   └── 📄 EDAsentiment+TA.ipynb
├── 📁 docs/                       # Documentation
│   ├── 📄 orderbook_analysis.md
│   └── 📄 notes.md
├── 📁 .github/workflows/          # GitHub Actions
│   └── 📄 bitcoin-signal.yml
├── 📄 requirements.txt
└── 📄 README.md
```

## 🚀 Quick Start

### 1. Setup Environment
```bash
# Clone repository
git clone <your-repo-url>
cd AlpabrosCrypto

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Analysis Scripts

#### Sentiment + Technical Analysis (Production)
```bash
# Single run
python AlphaCrypto.py

# Continuous 4-hour scheduling
python AlphaCrypto.py --schedule
```

#### Order Book Analysis (Development)
```bash
# Single run
python src/AlphaCrypto_OrderBook.py

# Continuous 15-second collection
python src/AlphaCrypto_OrderBook.py --continuous
```

### 3. Explore Data
```bash
# Start Jupyter notebook
jupyter notebook notebooks/

# Open EDAOrderbook.ipynb for order book analysis
# Open EDAsentiment+TA.ipynb for sentiment analysis
```

## 📊 Data Collection

### Sentiment + TA Script (AlphaCrypto.py)
- **Frequency**: Every 4 hours
- **Data Sources**: Tavily API (news), OpenAI (sentiment), CCXT (price data)
- **Outputs**: `signal.json`, `report.md`, `features.csv`, `audit.log`
- **GitHub Actions**: Automated execution every 4 hours

### Order Book Script (AlphaCrypto_OrderBook.py)
- **Frequency**: Every 1 minute (data collection), 5 minutes (analysis)
- **Data Sources**: Coinbase, Kraken, Bitfinex (order book + trades)
- **Outputs**: Order book data, trade data, features, signals
- **Status**: Development/testing phase

## 🔧 Configuration

### Environment Variables
Create a `.env` file with:
```
TAVILY_API_KEY=your_tavily_key
OPENAI_API_KEY=your_openai_key
SMTP_USER=your_email
SMTP_PASS=your_password
SMTP_TO=recipient_email
```

### File Paths
- **Production files**: Root directory (for GitHub Actions compatibility)
- **Development files**: Organized in `data/` subdirectories
- **Notebooks**: `notebooks/` directory with updated paths

## 📈 Analysis Methods

### 1. Sentiment Analysis
- **News Sources**: Tavily API for Bitcoin news
- **AI Classification**: GPT-4.1-mini for sentiment scoring
- **Time Windows**: Recent (2h) vs Background (6-12h)
- **Weighting**: 75% recent + 25% background

### 2. Technical Analysis
- **Indicators**: RSI, MACD, EMA crosses, Bollinger Bands, Stochastic
- **Timeframe**: 3-day lookback, 1-hour intervals
- **Features**: 15+ technical indicators
- **Optimization**: Crypto-specific thresholds

### 3. Order Book Analysis
- **Features**: 21 microstructure indicators
- **Data**: Order book depth, trade flow, price impact
- **Prediction**: 1-hour ahead price direction
- **Frequency**: High-frequency data collection

## 🎯 Prediction Outputs

### Signal Format
```json
{
  "timestamp": "2025-09-22T14:27:21.866841+00:00",
  "symbol": "BTC/USDT",
  "direction": "bullish|bearish|neutral",
  "confidence": 0.75,
  "reasoning": "Feature analysis explanation"
}
```

### Confidence Levels
- **High (0.7+)**: Strong signal with clear indicators
- **Medium (0.4-0.7)**: Moderate signal strength
- **Low (0.3-0.4)**: Weak or conflicting signals

## 📋 Development Workflow

### 1. Data Collection
- **Production**: Automated via GitHub Actions
- **Development**: Manual execution for testing

### 2. Analysis
- **Jupyter notebooks**: Interactive data exploration
- **Feature engineering**: Continuous improvement
- **Model validation**: Backtesting and performance metrics

### 3. Deployment
- **Production script**: Stable, tested, automated
- **Development scripts**: Experimental features
- **Documentation**: Updated with changes

## 🔍 Monitoring

### Data Quality
- **Collection rates**: Monitor data completeness
- **Feature stability**: Track feature variance
- **Signal quality**: Validate prediction accuracy

### Performance Metrics
- **Direction accuracy**: Target >55% (vs 50% random)
- **Confidence calibration**: High confidence = high accuracy
- **Signal timing**: Early warning capability

## 📚 Documentation

- **`docs/orderbook_analysis.md`**: Order book methodology
- **`docs/notes.md`**: Development notes and ideas
- **Jupyter notebooks**: Interactive analysis examples
- **Code comments**: Inline documentation

## 🤝 Contributing

1. **Fork the repository**
2. **Create feature branch**: `git checkout -b feature/new-feature`
3. **Make changes**: Follow existing code style
4. **Test thoroughly**: Ensure no production disruption
5. **Submit pull request**: Describe changes and impact

## ⚠️ Important Notes

- **Production script** (`AlphaCrypto.py`) must remain in root directory for GitHub Actions
- **File paths** are configured for the new structure
- **Data directories** are created automatically
- **Backup data** before major changes

## 📞 Support

For questions or issues:
1. Check existing documentation
2. Review Jupyter notebook examples
3. Examine code comments
4. Create GitHub issue with details

---

*AlpabrosCrypto v1.0 - Advanced BTC prediction using multiple data sources and analysis methods*