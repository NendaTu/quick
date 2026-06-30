# Bitget USDT-M Futures Trading Bot

A high-performance algorithmic trading system for Bitget USDT-M Futures, featuring multi-timeframe technical analysis, institutional-grade pattern recognition, and a robust A/B testing suite.

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd bitget-futures-bot
   ```

2. **Set up a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   Create a `.env` file in the root directory (essential for API access and mode configuration):
   ```env
   BITGET_API_KEY=your_api_key
   BITGET_SECRET_KEY=your_secret_key
   BITGET_PASSPHRASE=your_passphrase
   MODE=paper  # or "live"
   ```

## Usage

### Standard Run
Execute the bot using the primary configuration in `config.py`:
```bash
python main.py
```

### Backtesting
Backtest individual technical analysis conditions against historical data.

```bash
# Backtest a specific candle pattern (recursively searches ta/)
python backtest.py candle/engulfing

# Backtest with strategy parameters
python backtest.py sentiment 10 30

# Backtest with a specific date range
python backtest.py candle/engulfing_total 2026-05-01 2026-06-01

# Advanced: Confluence Chaining (use -> for sequences)
python backtest.py "candle/engulfing -> fvg 3 25"
```

The system will automatically download missing historical data and save it to the shared database.

### A/B Testing (Comparison)
The `compare.py` tool allows you to run multiple strategy variants concurrently against the same real-time data feed.

#### Method 1: CLI Overrides
Compare the baseline (`config.py`) against specific parameter changes:
```bash
# Compare root config vs one override
python compare.py SL_MOVE=0.01

# Compare root config vs multiple different values for the same parameter
python compare.py SL_MOVE=0.005 SL_MOVE=0.01 SL_MOVE=0.02

# Mix multiple parameter overrides
python compare.py "SL_MOVE=0.01, TP_MOVE=0.02" "SL_MOVE=0.005, TP_MOVE=0.01"
```

#### Method 2: Config Files
Compare the baseline against full configuration snapshots stored in `compare/configs/`:
1. Place your variant files (e.g., `aggressive.py`, `conservative.py`) in `compare/configs/`.
2. Run the comparison:
   ```bash
   python compare.py config
   ```

#### Stopping and Reporting
Press `CTRL+C` at any time to stop the comparison. The bot will print a final side-by-side table showing PnL, ROI%, Win Rate, Trade Count, and Equity for all variants.

## Infrastructure

- **`compare/logs/`**: Contains isolated trade logs for each variant during A/B testing.
- **`market_data.db`**: SQLite database for persistent storage (standard runs only).
- **`docs/archived/`**: Historical project documentation.

## Metrics tracked in Comparisons
- **PnL (USDT)**: Net profit/loss inclusive of all fees and slippage.
- **ROI%**: Return on starting equity.
- **Win% (TP)**: Overall win rate, with the percentage of direct Take-Profit hits in parentheses.
- **Trades**: Total number of completed trades.
- **Open**: Current number of open positions.
- **Equity**: Final account balance.
