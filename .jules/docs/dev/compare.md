# A/B Comparison System Documentation

The `compare.py` tool allows running multiple strategy variants concurrently against a real-time data feed. It provides isolated performance metrics for each variant, including PnL, Win Rate, and ROI.

## Operating Modes

### 1. CLI Overrides
Test small parameter changes by passing them directly to the command:
```bash
python compare.py SL_MOVE=0.01 TP_MOVE=0.02
```
This creates a "Baseline" (from `config.py`) and a "Var_1" with your changes.

### 2. Full Config Files
Test entire strategy snapshots by placing files in `compare/configs/`:
```bash
python compare.py config
```
Each `.py` file in that directory becomes a tested variant.

## Architecture

### DataCoordinator
- Creates a single WebSocket connection to Bitget.
- Performs a global "warm-up" (fetching initial OHLCV history).
- Multiplexes incoming market ticks to all active variants via `multiprocessing.Queue`.

### VariantRunner
- Each variant runs in its own OS process for complete isolation.
- It patches the `config` module in its local memory space before initializing the engine.
- Logs its activity to `compare/logs/[variant_id].log`.

## Metrics
The system updates a real-time console table with:
- **PnL (USDT)**: Net profit after fees and slippage.
- **ROI%**: Percentage return on initial equity.
- **Win% (TP)**: Overall win rate, with the direct Take-Profit hit percentage in parentheses.
- **Trades**: Total completed trade count.

## Shutdown
Pressing `CTRL+C` signals all subprocesses to stop gracefully, collects final statistics, and prints a summary table identifying the winner.
