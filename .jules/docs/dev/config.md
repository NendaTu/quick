# Configuration System Documentation

The `config.py` file is the central source of truth for all global settings, risk parameters, and execution rules.

## Core Sections

### Account & Risk
- `INITIAL_EQUITY`: The starting balance for paper and comparison runs.
- `RISK_PER_TRADE`: Fraction of balance risked per trade (used to calculate position size relative to SL distance).
- `MAX_CONCURRENT_POSITIONS`: Limits exposure by capping total open trades.
- `DRAWDOWN_LIMIT`: Safety kill-switch if equity drops too far from peak.

### Execution
- `ENTRY_ORDER_TYPE`: Use `limit` for maker entries or `market` for taker.
- `LIMIT_CHASE_TIMEOUT`: How long a limit entry stays open before converting to market or cancelling.
- `MAKER_FEE` / `TAKER_FEE`: Critical for accurate PnL and ROE math.
- `EXPECTED_SLIPPAGE`: Anticipated price movement for taker orders.

### Strategy Hardening (Gates)
Toggles that restrict entries based on specific market conditions:
- `RESTRICT_IMBALANCE`: Requires a minimum order book imbalance.
- `RESTRICT_HTF_BIAS`: Enforces alignment with Higher Timeframe (4H/1D) trend.
- `RESTRICT_VOLUME_INFLUX`: Requires recent volume spikes.

### Multi-Timeframe (MTF)
- `ACTIVE_TIMEFRAME`: The primary timeframe for execution and candle generation.
- `AVAILABLE_TIMEFRAMES`: List of timeframes the system fetches and maintains.

## Best Practices
- **Overrides**: Use `compare.py` CLI arguments or variant files to override these values without editing the root file.
- **Safety**: The system includes a startup check for `TARGET_NET_ROE` to ensure it's entered as a decimal (0.05) rather than a percentage (5.0).
- **Refactoring**: When adding new technical indicators, place their local constants (like Periods or Multipliers) inside the relevant `ta/` file instead of `config.py` to keep the configuration clean.
