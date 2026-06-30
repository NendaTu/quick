"""
Engulfing Body Strategy

How it works:
1. This strategy looks for a "Bullish" or "Bearish" engulfing pattern where only the 'body'
   (the rectangle part between Open and Close) is considered.
2. A Bullish signal occurs when a green candle's body completely covers the previous red candle's body.
3. A Bearish signal occurs when a red candle's body completely covers the previous green candle's body.
4. The strategy calculates a Take Profit (TP) target to net a specific profit (default +1% ROE)
   after paying all exchange fees and accounting for slippage.
5. The Stop Loss (SL) is placed slightly outside the extreme of the engulfing candle to protect capital.
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
