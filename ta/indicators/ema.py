"""
Exponential Moving Average (EMA) Strategy (Filter)

How it works:
1. This is a "Trend Filter" strategy. It ensures that trades are only taken
   when the short-term momentum is aligned with the long-term trend.
2. It compares two EMAs:
   - Short EMA (Default 20): Represents fast, recent price action.
   - Long EMA (Default 50): Represents the intermediate trend.
3. Signal Logic:
   - Bullish (Buy): Returns "buy" if the Short EMA is ABOVE the Long EMA.
   - Bearish (Sell): Returns "sell" if the Short EMA is BELOW the Long EMA.
4. Backtesting command: `python backtest.py "ema [short] [long] + [trigger]"`
   - Example: `"ema 20 50 + engulfing"`
"""

from typing import List, Dict, Optional
import config

# --- Configuration ---
ENABLED = True

# Default Strategy Settings
DEFAULT_SHORT = 20
DEFAULT_LONG = 50

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for EMA Alignment filter.
    """
    if len(ohlcv) < DEFAULT_LONG:
        return None

    # Parse Parameters
    short_p = int(params[0]) if params and len(params) > 0 else DEFAULT_SHORT
    long_p = int(params[1]) if params and len(params) > 1 else DEFAULT_LONG

    prices = [c['c'] for c in ohlcv]
    ema_s = compute_ema(prices, short_p)
    ema_l = compute_ema(prices, long_p)

    side = "buy" if ema_s > ema_l else "sell"

    return {
        "side": side,
        "entry_price": ohlcv[-1]['c'],
        "stop_price": 0, # Not used for filter
        "exit_price": 0, # Not used for filter
        "metadata": {"ema_short": ema_s, "ema_long": ema_l}
    }

def compute_ema(prices: List[float], period: int) -> float:
    if not ENABLED or not prices:
        return 0.0
    if len(prices) < period:
        return sum(prices) / len(prices)

    k = 2.0 / (period + 1)
    # Use a simple moving average as the initial EMA value for better seeding
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = (p - ema) * k + ema
    return ema
