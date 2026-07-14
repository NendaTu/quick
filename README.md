# Bitget USDT-M Futures Trading Bot

A high-performance algorithmic trading system for Bitget USDT-M Futures, featuring multi-timeframe technical analysis, institutional-grade pattern recognition, unified scoring confluence gates, and a robust A/B testing suite.

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

   # Optional: Demo Mode Credentials
   BITGET_API_KEY_DEMO=your_demo_api_key
   BITGET_SECRET_KEY_DEMO=your_demo_secret_key
   BITGET_PASSPHRASE_DEMO=your_demo_passphrase

   MODE=paper  # or "demo" or "live"
   ```

---

## Core Innovations & Architecture

### 1. Unified Entry Scoring Engine
The bot features a **continuous, unified scoring engine** that replaces rigid binary `RESTRICT_*` flags.
- **Continuous Evaluation**: Technical indicators (RSI, ADX, MACD, DRT, etc.) are converted to scores from `-100` (max bearish) to `+100` (max bullish).
- **Weighted Average Aggregation**: Indictors are aggregated using a robust weighted average. User-configured weights (e.g., `WEIGHT_IMBALANCE = 1.5`, `WEIGHT_RSI = 1.0`) act as multipliers for the adaptive learning model's dynamic weights.
- **Entry Gating**: Signals must exceed the `ENTRY_SCORE_THRESHOLD` (default `15.0`) to trigger an entry. Truly adverse conditions pull the aggregate score down, safely blocking trades.
- **Quality Penalties**: Non-directional quality factors (like spread, ATR volatility, and depth volume) act as side-dependent penalties, pulling the score away from the direction's passing threshold.
- **Logging**: All evaluations (taken and rejected) are written to `docs/temp/[timestamp].metrics-log.txt` in a standardized 42-column CSV schema.

### 2. "Zombie Sweep" Prevention
In high-frequency sweep-reversal strategies, there is a risk that after a successful trade and virtual cooldown expiration, the same historical sweep is entered repeatedly.
- Once a sweep is traded, its timestamp is saved: `last_traded_sweep_ts = sweep_ts`.
- Any subsequent sweeps at or before this timestamp are **strictly blocked**, eliminating duplicate "echo" entries and protecting your capital in choppy markets.

### 3. High-Fidelity Backtesting & Virtual-Time Logging
- **Time-Scale Correction**: Cooldowns and state transitions are compared using virtual candle timestamps instead of real system clock time, ensuring perfect alignment in backtesting.
- **Virtual Time Logs**: Console output and file logs automatically prepend the active backtest virtual date next to the real system date-time:
  `2026-07-13 09:52:32 [2026-05-01 00:00:00] backtest HEARTBEAT ...`

---

## Usage

### Standard Run
Execute the bot using a specific strategy. Strategies are located in the `strategies/` directory.

```bash
# Run with a specific strategy and mode
python3 main.py --strategy killzone_sweep.1.mustafa --mode paper

# Run with Demo Mode (uses Demo API keys and environment)
python3 main.py --strategy scalper.1.jules --mode demo

# Run with the ATR-based range strategy
python3 main.py --strategy range_sweep_ATR.1.mustafa --mode paper
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
- **`ta/`**: Stateless indicators, patterns, feature extractor, and continuous scoring engine.
- **`compare_data/logs/`**: Contains isolated trade logs for each variant during A/B testing.
- **`market_data.db`**: SQLite database for persistent storage (standard runs only).
- **`docs/`**: Historical project documentation and focus logs.

## Metrics tracked in Comparisons
- **PnL (USDT)**: Net profit/loss inclusive of all fees and slippage.
- **ROI%**: Return on starting equity.
- **Win% (TP)**: Overall win rate, with the percentage of direct Take-Profit hits in parentheses.
- **Trades**: Total number of completed trades.
- **Open**: Current number of open positions.
- **Equity**: Final account balance.
