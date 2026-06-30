# Backtesting System Documentation

The `backtest.py` system allows for high-fidelity simulation of Technical Analysis (TA) conditions against historical Bitget USDT-M Futures data. It is designed to be modular, automated, and mathematically consistent with live trading.

## How to Run a Backtest

Basic command:
```bash
python backtest.py "[strategy_query]" [start_date] [end_date]
```

> **IMPORTANT**: Always wrap your strategy query in quotes (e.g. `"A > B"`) to prevent your terminal from misinterpreting the `>` symbol as a command to overwrite a file.

### Strategy Resolution
The system recursively searches the `ta/` directory. It includes a "singular-to-plural" mapping for convenience:
- `candle/engulfing` resolves to `ta/candles/engulfing.py`
- `pattern/fvg` resolves to `ta/patterns/fvg.py`
- `engulfing` will find all matches and prompt you if ambiguous.

## Confluence Chaining (Advanced)
You can combine multiple strategies using two operators:
1.  **Simultaneous (`+`)**: Both conditions must happen on the exact same candle.
2.  **Sequential (`>`)**: The first condition happens, then the next must happen within **5 candles** (configurable in `backtest.py`).

### Directional Rules
- **Strict (Default)**: All items in the chain must point in the same direction (e.g., all Bullish).
- **Ignore Direction (`~`)**: Add a tilde to an item (e.g. `fvg~`) to allow it to trigger in either direction regardless of the chain.
- **Open (`open`)**: Add "open" to the end of the query to allow the entire chain to be direction-agnostic.

### Examples
- **Combination**: `"engulfing + sentiment 10 20"` (Must meet both on one candle).
- **Sequence**: `"engulfing > fvg 3 25"` (Engulfing first, then FVG follows).
- **Mixed**: `"engulfing + sentiment 10 20 > fvg 3 25 1.5"` (Combined signal followed by FVG with 1.5 RRR).

### Date Range
- **Default**: The last 30 days (for speed).
- **Global Range**: June 1, 2022 to June 1, 2026.
- **Custom**: Provide `YYYY-MM-DD` as the 2nd and 3rd arguments.

## The Strategy Template (`get_signal`)

To make a TA condition "backtestable," it must implement the following function interface:

```python
from typing import List, Dict, Optional

def get_signal(ohlcv: List[dict], timeframe: str) -> Optional[Dict]:
    """
    Args:
        ohlcv: List of candles {'ts', 'o', 'h', 'l', 'c', 'v'}
        timeframe: e.g., '1m', '5m', '15m'

    Returns:
        {
            "side": "buy" | "sell",
            "entry_price": float,
            "stop_price": float,
            "exit_price": float, # The Take Profit target
            "metadata": dict     # Optional extra logging info
        } or None
    """
```

### Implementation Tips
- **Consistency**: Use `tools/trading_utils.py` to calculate target prices for specific ROEs.
- **State**: Backtesting is stateless per candle; the `ohlcv` list provides the necessary history.
- **Slippage/Fees**: The backtest engine handles these automatically based on `config.py` settings. You only need to provide the price levels.

## Data Management
The system automatically detects missing data for the requested range/asset/timeframe and downloads it from Bitget's history API.
- **Persistence**: Data is saved to `market_data.db`.
- **Assets**: Defaults to ETH, HBAR, UNI, GRT (editable in `backtest.py`).
- **Timeframes**: Defaults to 1m, 3m, 5m, 15m.

## Math & Reporting
- **Win% (L/S)**: Net win rate for Long and Short positions respectively.
- **PnL (L/S)**: Cumulative Net PnL for Long and Short positions.
- **ROE%**: Calculated using 20x leverage as a standard baseline for comparison across different assets.
- **Position Sizing**: Derived strictly from `config.py` settings:
    - **Risk**: Uses `RISK_PER_TRADE` (fraction of equity).
    - **Balance**: Starts with `INITIAL_EQUITY` and compounds based on realized PnL.
    - **Algorithm**: Uses `tools/trading_utils.py:calculate_position_size`, which is "fee-aware"—it accounts for entry and exit fees when calculating the maximum quantity allowed for a given risk fraction.
- **Fees**: Accounts for Maker (Limit TP) and Taker (Market/SL) fees as defined in `config.py`.
- **Slippage**: Applies `EXPECTED_SLIPPAGE` from `config.py` to all taker-executed legs.
