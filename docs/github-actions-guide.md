# GitHub Actions Guide for Order Book Collection

This guide explains how to use GitHub Actions to run the order book data collection script.

## 🚀 Available Workflows

### 1. **Order Book Microstructure Analysis** - Regular Collection
- **File**: `orderbook-collection.yml`
- **Schedule**: Every 1 minute
- **Purpose**: Order book data collection and microstructure analysis
- **Duration**: ~2 minutes per run
- **Output**: Order book data, features, signals

### 2. **Extended Order Book Microstructure Analysis** - Extended Collection
- **File**: `orderbook-extended.yml`
- **Trigger**: Manual only
- **Purpose**: Long-duration order book data collection
- **Duration**: 1-240 minutes (configurable)
- **Output**: Extended microstructure dataset

### 3. **Bitcoin Signal Analysis** - Production Sentiment+TA
- **File**: `bitcoin-signal.yml`
- **Schedule**: Every 4 hours
- **Purpose**: Production sentiment analysis and technical analysis
- **Duration**: ~10 minutes per run
- **Output**: BTC price predictions

## 📋 How to Use

### **Option 1: Automatic Collection (Recommended)**

The order book collection will run automatically every 15 minutes. No action needed!

**What happens:**
1. GitHub Actions triggers every 15 minutes
2. Collects order book and trade data
3. Calculates 21 microstructure features
4. Generates 1-hour price prediction
5. Uploads data as artifacts

### **Option 2: Manual Collection**

#### **Regular Collection:**
1. Go to **Actions** tab in GitHub
2. Select **"Order Book Microstructure Analysis"**
3. Click **"Run workflow"**
4. Click **"Run workflow"** button

#### **Extended Collection:**
1. Go to **Actions** tab in GitHub
2. Select **"Extended Order Book Microstructure Analysis"**
3. Click **"Run workflow"**
4. Configure parameters:
   - **Collection duration**: 60 minutes (default)
   - **Collection interval**: 15 seconds (default)
5. Click **"Run workflow"** button

### **Option 3: Local Collection**

```bash
# Single analysis
python scripts/run_orderbook.py single

# Continuous collection (15-second intervals)
python scripts/run_orderbook.py continuous

# Extended collection (60 minutes, 15-second intervals)
python scripts/run_orderbook.py extended --duration 60 --interval 15

# Custom extended collection (2 hours, 30-second intervals)
python scripts/run_orderbook.py extended --duration 120 --interval 30
```

## 📊 Data Collection Details

### **Collection Frequency:**
- **Automatic**: Every 1 minute
- **Data points per day**: ~1,440 collections
- **Data retention**: 30 days (artifacts)

### **Data Collected:**
- **Order book data**: Top 20 bid/ask levels
- **Trade data**: Last 100 trades
- **Features**: 21 microstructure indicators
- **Signals**: 1-hour price predictions

### **File Outputs:**
```
data/raw/
├── orderbook_data.csv      # Order book snapshots
└── trades_data.csv         # Trade records

data/processed/
└── orderbook_features.csv  # Calculated features

data/outputs/
├── orderbook_signals.json  # Prediction signals
└── reports/
    └── orderbook_report.md # Analysis reports
```

## 🔧 Configuration

### **Environment Variables:**
No additional environment variables needed for order book collection (uses public APIs).

### **Workflow Settings:**
- **Timeout**: 20 minutes (regular), 300 minutes (extended)
- **Python version**: 3.10
- **Dependencies**: From requirements.txt
- **Artifact retention**: 30 days (data), 7 days (logs)

## 📈 Monitoring Collection

### **Check Collection Status:**
1. Go to **Actions** tab
2. Look for **"Order Book Data Collection"** runs
3. Green checkmark = successful
4. Red X = failed (check logs)

### **Download Data:**
1. Go to **Actions** tab
2. Click on a successful run
3. Scroll to **"Artifacts"** section
4. Download **"orderbook-data-[number]"**

### **View Logs:**
1. Go to **Actions** tab
2. Click on a run
3. Click on **"collect-orderbook-data"** job
4. View step-by-step logs

## ⚠️ Important Notes

### **Resource Limits:**
- **GitHub Actions**: 2,000 minutes/month (free tier)
- **Regular collection**: ~2 minutes per run = ~2,880 minutes/month
- **Extended collection**: Use sparingly (high resource usage)
- **Note**: Will exceed free tier - consider upgrading or reducing frequency

### **Data Storage:**
- **Artifacts**: Stored on GitHub (30-day retention)
- **Local storage**: Not persistent between runs
- **Backup**: Download important data regularly

### **Error Handling:**
- **Exchange failures**: Automatic fallback to other exchanges
- **Network issues**: Retry with 5-second delay
- **Timeout**: Jobs will stop after timeout period

## 🚨 Troubleshooting

### **Common Issues:**

#### **1. Workflow Fails to Start**
- Check if workflow file is in `.github/workflows/`
- Verify YAML syntax is correct
- Check GitHub Actions permissions

#### **2. Collection Errors**
- Check exchange API availability
- Verify internet connection
- Review error logs in Actions tab

#### **3. Missing Data**
- Check if workflow is enabled
- Verify schedule is correct
- Look for failed runs in Actions tab

#### **4. High Resource Usage**
- Reduce collection frequency
- Use shorter extended collection periods
- Monitor GitHub Actions usage

### **Debug Steps:**
1. **Check workflow status** in Actions tab
2. **Review logs** for error messages
3. **Test locally** with `python scripts/run_orderbook.py single`
4. **Verify dependencies** are installed correctly

## 📞 Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review GitHub Actions logs
3. Test the script locally first
4. Create a GitHub issue with details

---

*This guide covers all aspects of running order book collection via GitHub Actions. The system is designed to be robust and handle most common issues automatically.*