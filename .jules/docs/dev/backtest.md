# Backtesting System Documentation

The `backtest.py` system allows for high-fidelity simulation of Technical Analysis (TA) conditions against historical Bitget USDT-M Futures data. It is designed to be modular, automated, and mathematically consistent with live trading.

## How to Run a Backtest

Basic command:
```bash
python backtest.py [strategy_query] [start_date] [end_date]
```

### Strategy Resolution
The system recursively searches the `ta/` directory. It includes a "singular-to-plural" mapping for convenience:
- `candle/engulfing` resolves to `ta/candles/engulfing.py`
- `pattern/fvg` resolves to `ta/patterns/fvg.py`
- `engulfing` will find all matches and prompt you if ambiguous.

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
- **Win% (TP)**: Calculated as the percentage of trades that yielded a positive Net PnL after all fees and slippage.
- **ROE%**: Calculated using 20x leverage as a standard baseline for comparison across different assets.
- **Position Sizing**: Derived strictly from `config.py` settings:
    - **Risk**: Uses `RISK_PER_TRADE` (fraction of equity).
    - **Balance**: Starts with `INITIAL_EQUITY` and compounds based on realized PnL.
    - **Algorithm**: Uses `tools/trading_utils.py:calculate_position_size`, which is "fee-aware"—it accounts for entry and exit fees when calculating the maximum quantity allowed for a given risk fraction.
- **Fees**: Accounts for Maker (Limit TP) and Taker (Market/SL) fees as defined in `config.py`.
- **Slippage**: Applies `EXPECTED_SLIPPAGE` from `config.py` to all taker-executed legs.
