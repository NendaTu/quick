"""
Sentiment Candle Strategy

How it works:
1. This strategy identifies "sentiment" based on where the candle's body is located
   relative to its total high-low range.
2. It takes two numbers as input:
   - Body Percentage: How much of the candle is the actual rectangle (Open to Close).
   - Offset Percentage: How close the body is to the High (for Bullish) or Low (for Bearish).
3. Example: `python backtest.py sentiment 10 30`
   - This looks for candles where the body is about 10% of the total size.
   - For a Bullish signal: The top of that body must be within the top 30% of the candle's range.
   - For a Bearish signal: The bottom of that body must be within the bottom 30% of the candle's range.
4. Leeway: The strategy includes a small "leeway" (default 1%) so that a "10 30" search also
   finds "9-11 29-31" matches, ensuring we don't miss close patterns.
"""

from typing import List, Dict, Optional
from tools.trading_utils import calculate_tp_for_roe
import config

# --- Configuration ---
DEFAULT_LEEWAY = 1.0 # +/- 1% allowance for parameters
TARGET_ROE = 0.01
SL_TICK_BUFFER = 0.0001 # 0.01% proxy

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
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
