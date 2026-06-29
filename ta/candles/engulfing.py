"""
Engulfing Body Strategy

Triggers when a candle body completely engulfs the previous candle's body.
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
            # SL: 1 tick below engulfing candle low
            # Using 0.01% as a proxy for "1 tick" since we don't have symbol-specific tick size here easily
            stop = curr['l'] * 0.9999

            # Target +1% ROE
            # Note: We assume 20x leverage for ROE target calculation if not specified
            tp = calculate_tp_for_roe(entry, 0.01, "buy", 20, entry_maker=False, exit_maker=True)

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
            stop = curr['h'] * 1.0001
            tp = calculate_tp_for_roe(entry, 0.01, "sell", 20, entry_maker=False, exit_maker=True)

            return {
                "side": "sell",
                "entry_price": entry,
                "stop_price": stop,
                "exit_price": tp,
                "metadata": {"type": "body_engulfing"}
            }

    return None
