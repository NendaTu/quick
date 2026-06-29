"""
Sentiment Candle Strategy

Analyzes candle body size relative to range and position relative to High/Low.
Example: python backtest.py sentiment 10 30
- Body <= 10% of Range
- Bullish: Body top within top 30% of Range
- Bearish: Body bottom within bottom 30% of Range
"""

from typing import List, Dict, Optional
from tools.trading_utils import calculate_tp_for_roe
import config

# --- Configuration ---
DEFAULT_LEEWAY = 1.0 # +/- 1% allowance for parameters
TARGET_ROE = 0.01
SL_TICK_BUFFER = 0.0001 # 0.01% proxy

def get_signal(ohlcv: List[dict], timeframe: str, params: List[str] = None) -> Optional[Dict]:
    if not params or len(params) < 2:
        return None

    try:
        target_body_pct = float(params[0])
        target_offset_pct = float(params[1])
    except ValueError:
        return None

    if len(ohlcv) < 1:
        return None

    curr = ohlcv[-1]
    high, low = curr['h'], curr['l']
    open_p, close_p = curr['o'], curr['c']
    range_p = high - low

    if range_p <= 0:
        return None

    body_size = abs(open_p - close_p)
    body_pct = (body_size / range_p) * 100

    # Body top/bottom offsets
    body_max = max(open_p, close_p)
    body_min = min(open_p, close_p)

    bullish_offset = ((high - body_max) / range_p) * 100
    bearish_offset = ((body_min - low) / range_p) * 100

    # Apply Leeway
    body_match = (target_body_pct - DEFAULT_LEEWAY) <= body_pct <= (target_body_pct + DEFAULT_LEEWAY)

    if body_match:
        # Check Bullish: Top of body near High
        if (target_offset_pct - DEFAULT_LEEWAY) <= bullish_offset <= (target_offset_pct + DEFAULT_LEEWAY):
            entry = close_p
            stop = low * (1 - SL_TICK_BUFFER)
            tp = calculate_tp_for_roe(entry, TARGET_ROE, "buy", 20, entry_maker=False, exit_maker=True)
            return {
                "side": "buy",
                "entry_price": entry,
                "stop_price": stop,
                "exit_price": tp,
                "metadata": {"body_pct": body_pct, "offset_pct": bullish_offset}
            }

        # Check Bearish: Bottom of body near Low
        if (target_offset_pct - DEFAULT_LEEWAY) <= bearish_offset <= (target_offset_pct + DEFAULT_LEEWAY):
            entry = close_p
            stop = high * (1 + SL_TICK_BUFFER)
            tp = calculate_tp_for_roe(entry, TARGET_ROE, "sell", 20, entry_maker=False, exit_maker=True)
            return {
                "side": "sell",
                "entry_price": entry,
                "stop_price": stop,
                "exit_price": tp,
                "metadata": {"body_pct": body_pct, "offset_pct": bearish_offset}
            }

    return None
