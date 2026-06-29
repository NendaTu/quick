"""
Total Engulfing Strategy (Full Candle)

Triggers when a candle body completely engulfs the entire previous candle (wick-to-wick).
TP is calculated to ensure +1% Net ROE.
SL is 1 tick outside the engulfing candle's range.
"""

from typing import List, Dict, Optional
from tools.trading_utils import calculate_tp_for_roe
import config

def get_signal(ohlcv: List[dict], timeframe: str) -> Optional[Dict]:
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
            stop = curr['l'] * 0.9999
            tp = calculate_tp_for_roe(entry, 0.01, "buy", 20, entry_maker=False, exit_maker=True)

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
            stop = curr['h'] * 1.0001
            tp = calculate_tp_for_roe(entry, 0.01, "sell", 20, entry_maker=False, exit_maker=True)

            return {
                "side": "sell",
                "entry_price": entry,
                "stop_price": stop,
                "exit_price": tp,
                "metadata": {"type": "total_engulfing"}
            }

    return None
