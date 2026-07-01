"""
Liquidity Sweep Strategy (Institutional Reversal)

How it works:
1. This is an "Institutional" reversal strategy. It identifies "Stop Hunts" where
   price briefly pokes through a major high or low to grab liquidity before reversing.
2. Buy Side Sweep: Price wicks above a major High (Buy Side Liquidity) then closes
   back below it with a bearish candle.
3. Sell Side Sweep: Price wicks below a major Low (Sell Side Liquidity) then closes
   back above it with a bullish candle.
4. Signal Logic:
   - Triggered immediately on the close of the reversal candle.
5. Stop Loss (SL): Placed 1 tick beyond the "Sweep Wick" (the extreme point of the reversal).
6. Take Profit (TP): Targets a specific net profit (default +1% ROE).
7. Backtesting command: `python backtest.py sweep [rrr_override]`
"""

from typing import List, Dict, Optional
from ta.patterns.liquidity import identify_liquidity
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
# Toggle to enable/disable sweep detection.
ENABLED = True

# Minimum break (%) required beyond the liquidity level to consider it a sweep.
SWEEP_MARGIN_PCT = 0.002

# Default Strategy Settings
DEFAULT_TARGET_ROE = 0.01
SL_TICK_BUFFER = 0.0001

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for Liquidity Sweep strategy.
    """
    if len(ohlcv) < 51:
        return None

    # Parse Parameters
    rrr_override = float(params[0]) if params and len(params) > 0 else None

    # 1. Identify Sweeps
    sweep_info = detect_sweeps(ohlcv)
    if not sweep_info.get('sweep_detected'):
        return None

    sweep_type = sweep_info['sweep_type']
    curr = ohlcv[-1]

    # 2. Map Sweep to Trade Direction
    # Buy Side Sweep (broke high) -> Sell
    # Sell Side Sweep (broke low) -> Buy
    if sweep_type == 'buy_side':
        entry_side = "sell"
        stop = curr['h'] * (1 + SL_TICK_BUFFER)
    else: # sell_side
        entry_side = "buy"
        stop = curr['l'] * (1 - SL_TICK_BUFFER)

    entry = curr['c']
    if stop == entry: return None

    # 3. Calculate TP
    entry_maker = (config.ENTRY_ORDER_TYPE == "limit")
    tp_maker = (config.TP_ORDER_TYPE == "limit")

    if rrr_override is not None:
        target_roe = calculate_target_roe_for_rrr(rrr_override, entry, stop, 20, entry_maker=entry_maker)
    else:
        target_roe = DEFAULT_TARGET_ROE

    tp = calculate_tp_for_roe(entry, target_roe, entry_side, 20, entry_maker=entry_maker, exit_maker=tp_maker)

    return {
        "side": entry_side,
        "entry_price": entry,
        "stop_price": stop,
        "exit_price": tp,
        "metadata": {"sweep_type": sweep_type, "sweep_level": sweep_info['sweep_level']}
    }

def detect_sweeps(ohlcv: List[dict]) -> Dict:
    """
    Checks for recent liquidity sweeps.
    """
    if not ENABLED or len(ohlcv) < 50:
        return {}

    # Identify liquidity pools based on preceding data (exclude current bar)
    liquidity = identify_liquidity(ohlcv[:-1], lookback=50)
    if not liquidity:
        return {}

    bsl = liquidity['bsl_level']
    ssl = liquidity['ssl_level']

    last = ohlcv[-1]
    sweep_type = None

    # 1. Buy Side Sweep (Liquidity Hunt)
    if last['h'] > bsl and last['c'] < bsl:
        if last['c'] < last['o']: # Bearish close
            sweep_type = 'buy_side'

    # 2. Sell Side Sweep
    elif last['l'] < ssl and last['c'] > ssl:
        if last['c'] > last['o']: # Bullish close
            sweep_type = 'sell_side'

    return {
        'sweep_detected': sweep_type is not None,
        'sweep_type': sweep_type,
        'sweep_level': bsl if sweep_type == 'buy_side' else (ssl if sweep_type == 'sell_side' else None),
        'sweep_timestamp': last['ts'] if sweep_type else None
    }
