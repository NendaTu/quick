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
Execute the bot using a specific strategy. Strategies are located in the `strategies/` directory.

```bash
# Run with a specific strategy and mode
python3 main.py --strategy killzone_sweep.1.mustafa --mode paper
```

### Backtesting
Backtest individual strategies or technical analysis conditions against historical data.

```bash
# Backtest a class-based strategy
python3 backtest.py killzone_sweep.1.mustafa

# Backtest with asset filtering and date range
python3 backtest.py killzone_sweep.1.mustafa 2026-05-01 2026-06-01 assets=ETHUSDT,UNIUSDT

# Backtest with parameter overrides
python3 backtest.py killzone_sweep.1.mustafa h1_strength=1

# Backtest a specific TA module (recursively searches ta/)
python3 backtest.py pattern/structure

# Advanced: Confluence Chaining (use -> for sequences)
python3 backtest.py "candle/engulfing -> fvg 3 25"
```

The system will automatically download missing historical data and save it to the shared database.

### A/B Testing (Comparison)
The `compare` tool allows you to run multiple strategy variants or parameter overrides concurrently.

#### Method 1: Strategy Comparison
Compare two different strategy files side-by-side:
```bash
./compare --strategy-a scalper.1.jules --strategy-b my_new_strat.1.dev
```

#### Method 2: CLI Overrides
Compare a strategy against specific parameter changes:
```bash
# Compare a strategy with different SL values
./compare --strategy scalper.1.jules SL_MOVE=0.01 SL_MOVE=0.02
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

- **`strategies/`**: Orchestration layer for trading logic.
- **`engine/`**: Core execution and routing logic.
- **`compare_data/logs/`**: Contains isolated trade logs for each variant during A/B testing.
- **`market_data.db`**: SQLite database for persistent storage (standard runs only).
- **`docs/archived/`**: Historical project documentation.

## Metrics tracked in Comparisons
- **PnL (USDT)**: Net profit/loss inclusive of all fees and slippage.
- **ROI%**: Return on starting equity.
- **Win% (TP)**: Overall win rate, with the percentage of direct Take-Profit hits in parentheses.
- **Trades**: Total number of completed trades.
- **Open**: Current number of open positions.
- **Equity**: Final account balance.
