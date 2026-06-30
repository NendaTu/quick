"""
Total Engulfing Strategy (Full Candle)

How it works:
1. This strategy is an aggressive version of the engulfing pattern. It requires the 'body'
   of the current candle to completely cover the 'entire' previous candle (from high wick to low wick).
2. A Bullish signal occurs when a green body swallows the previous candle's entire range.
3. A Bearish signal occurs when a red body swallows the previous candle's entire range.
4. Like the standard engulfing strategy, it sets a Take Profit (TP) to ensure a net +1% profit (ROE)
   and a Stop Loss (SL) just beyond the trigger candle's high or low.
"""

from typing import List, Dict, Optional
from tools.trading_utils import calculate_tp_for_roe
import config

# --- Configuration ---
TARGET_ROE = 0.01
SL_TICK_BUFFER = 0.0001 # 0.01% proxy

def get_signal(ohlcv: List[dict], timeframe: str, params: List[str] = None) -> Optional[Dict]:
    if len(ohlcv) < 2:
        return None

    prev = ohlcv[-2]
    curr = ohlcv[-1]

    # Current body vs Previous full range
    curr_body_high, curr_body_low = max(curr['o'], curr['c']), min(curr['o'], curr['c'])
    prev_full_high, prev_full_low = prev['h'], prev['l']

    # Check for Bullish Total Engulfing
    if curr['c'] > curr['o']: # Bullish candle
        if curr_body_high >= prev_full_high and curr_body_low <= prev_full_low:
            entry = curr['c']
            stop = curr['l'] * (1 - SL_TICK_BUFFER)
            tp = calculate_tp_for_roe(entry, TARGET_ROE, "buy", 20, entry_maker=False, exit_maker=True)

            return {
                "side": "buy",
                "entry_price": entry,
                "stop_price": stop,
                "exit_price": tp,
                "metadata": {"type": "total_engulfing"}
            }

    # Check for Bearish Total Engulfing
    if curr['c'] < curr['o']: # Bearish candle
        if curr_body_low <= prev_full_low and curr_body_high >= prev_full_high:
            entry = curr['c']
            stop = curr['h'] * (1 + SL_TICK_BUFFER)
            tp = calculate_tp_for_roe(entry, TARGET_ROE, "sell", 20, entry_maker=False, exit_maker=True)

            return {
                "side": "sell",
                "entry_price": entry,
                "stop_price": stop,
                "exit_price": tp,
                "metadata": {"type": "total_engulfing"}
            }

    return None
