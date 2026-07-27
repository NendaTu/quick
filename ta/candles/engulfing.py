"""
1. Summary: Stateless pattern recognizer for body-only engulfing candles.
2. Description: Identifies engulfing candlestick signals where only the body overlaps the previous bar body. Disregards candle wicks for a conservative entry signal.
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

    # Body definitions
    prev_open, prev_close = prev['o'], prev['c']
    curr_open, curr_close = curr['o'], curr['c']

    prev_high, prev_low = max(prev_open, prev_close), min(prev_open, prev_close)
    curr_high, curr_low = max(curr_open, curr_close), min(curr_open, curr_close)

    # Check for Bullish Engulfing Body
    # Current is green, previous was red, current body covers previous body
    if curr_close > curr_open and prev_open > prev_close:
        if curr_close >= prev_open and curr_open <= prev_close:
            # Entry at close of engulfing candle
            entry = curr_close
            # SL: configurable buffer below engulfing candle low
            stop = curr['l'] * (1 - SL_TICK_BUFFER)

            # Target ROE
            tp = calculate_tp_for_roe(entry, TARGET_ROE, "buy", 20, entry_maker=False, exit_maker=True)

            return {
                "side": "buy",
                "entry_price": entry,
                "stop_price": stop,
                "exit_price": tp,
                "metadata": {"type": "body_engulfing"}
            }

    # Check for Bearish Engulfing Body
    if curr_close < curr_open and prev_open < prev_close:
        if curr_close <= prev_open and curr_open >= prev_close:
            entry = curr_close
            stop = curr['h'] * (1 + SL_TICK_BUFFER)
            tp = calculate_tp_for_roe(entry, TARGET_ROE, "sell", 20, entry_maker=False, exit_maker=True)

            return {
                "side": "sell",
                "entry_price": entry,
                "stop_price": stop,
                "exit_price": tp,
                "metadata": {"type": "body_engulfing"}
            }

    return None
