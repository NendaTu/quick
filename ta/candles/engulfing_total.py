"""
1. Summary: Stateless pattern recognizer for total candle engulfing.
2. Description: Identifies aggressive engulfing setups where the active candle body completely engulfs both the previous body and wicks.
3. Context: Utilized by candle patterns analysis and indicators features pipeline.
"""
from typing import List, Dict, Optional
from tools.trading_utils import calculate_tp_for_roe
import config

# --- Configuration ---
TARGET_ROE = 0.01
SL_TICK_BUFFER = 0.0001 # 0.01% proxy

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
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
