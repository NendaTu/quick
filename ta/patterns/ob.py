"""
Order Block (OB) and Breaker Market Structure (BMS) Strategy

How it works:
1. This strategy identifies "Order Blocks"—price zones where institutional
   buying or selling occurred before a strong, fast move.
2. A Bullish OB is a bearish candle followed by a rapid upward "impulse"
   that breaks its high.
3. A Bearish OB is a bullish candle followed by a rapid downward "impulse"
   that breaks its low.
4. Signal Logic:
   - Entry triggers when the current candle "touches" the range of an active
     (unfilled) Order Block.
5. Stop Loss (SL): Placed 1 tick beyond the "local extreme" (the valley or peak
   surrounding the OB) to protect against common liquidity "sweeps" where
   price briefly pokes beyond the block before reversing.
6. Take Profit (TP): Targets a specific net profit (default +1% ROE).
7. Backtesting command: `python backtest.py ob [rrr_override]`
"""

from typing import List, Dict, Optional
from ta.indicators.atr import compute_atr
from ta.patterns.swings import detect_swings
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
# Toggle to enable/disable Order Block detection.
ENABLED = True

# Impulse candle range must be > IMPULSE_MULT * ATR.
IMPULSE_MULT = 1.5

# Margin (%) required to invalidate an OB and turn it into a Breaker.
INVALIDATION_MARGIN = 0.001

# Default Strategy Settings
DEFAULT_TARGET_ROE = 0.01
SL_TICK_BUFFER = 0.0001

def get_signal(ohlcv: List[dict], timeframe: str, params: List[str] = None) -> Optional[Dict]:
    """
    Backtesting entry point for Order Block strategy.
    """
    if len(ohlcv) < 21:
        return None

    # Parse Parameters
    rrr_override = float(params[0]) if params and len(params) > 0 else None

    # 1. Identify OBs using the core logic
    # We need to find the raw list of OB objects, so we'll look at the
    # internal logic of detect_order_blocks

    closed_ohlcv = ohlcv[:-1]
    highs = [c['h'] for c in closed_ohlcv]
    lows = [c['l'] for c in closed_ohlcv]
    closes = [c['c'] for c in closed_ohlcv]
    atr = compute_atr(highs, lows, closes)

    # Re-identify active OBs to find their specific price ranges
    obs = []
    for i in range(1, len(closed_ohlcv) - 1):
        prev = closed_ohlcv[i-1]
        curr = closed_ohlcv[i]
        nxt = closed_ohlcv[i+1]
        if curr['c'] < curr['o']: # Potential Bullish OB
            if (nxt['h'] - nxt['l']) > IMPULSE_MULT * atr and nxt['c'] > curr['h']:
                obs.append({'type': 'bullish', 'top': curr['h'], 'bottom': curr['l'], 'index': i, 'state': 'active'})
        elif curr['c'] > curr['o']: # Potential Bearish OB
            if (nxt['h'] - nxt['l']) > IMPULSE_MULT * atr and nxt['c'] < curr['l']:
                obs.append({'type': 'bearish', 'top': curr['h'], 'bottom': curr['l'], 'index': i, 'state': 'active'})

    if not obs: return None

    # Filter for active only (not mitigated in history)
    active_obs = []
    for ob in obs:
        mitigated = False
        post_ob_candles = closed_ohlcv[ob['index']+2:]
        for pc in post_ob_candles:
            if pc['h'] >= ob['bottom'] and pc['l'] <= ob['top']:
                mitigated = True
                break
        if not mitigated:
            active_obs.append(ob)

    if not active_obs: return None

    # 2. Check for "Touch" on current candle
    curr = ohlcv[-1]
    entry_side = None
    target_ob = None

    for ob in reversed(active_obs):
        if ob['type'] == 'bullish' and curr['l'] <= ob['top'] and curr['c'] > ob['bottom']:
            entry_side = "buy"
            target_ob = ob
            break
        elif ob['type'] == 'bearish' and curr['h'] >= ob['bottom'] and curr['c'] < ob['top']:
            entry_side = "sell"
            target_ob = ob
            break

    if not entry_side: return None

    # 3. SL: Local Swing Extreme (protect against sweeps)
    entry = curr['c']
    swings = detect_swings(ohlcv[-50:], strength=2)

    if entry_side == 'buy':
        if not swings['lows']: return None
        # SL is one tick below the local valley that created the OB
        stop = swings['lows'][-1]['price'] * (1 - SL_TICK_BUFFER)
    else: # sell
        if not swings['highs']: return None
        stop = swings['highs'][-1]['price'] * (1 + SL_TICK_BUFFER)

    if stop == entry: return None

    # 4. Calculate TP
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
        "metadata": {"ob_index": target_ob['index'], "ob_range": f"{target_ob['bottom']:.2f}-{target_ob['top']:.2f}"}
    }

def detect_order_blocks(ohlcv: List[dict]) -> Dict:
    """
    Identifies order blocks and breaker blocks.
    Only considers closed candles for OB formation.
    """
    if not ENABLED or len(ohlcv) < 21:
        return {}

    closed_ohlcv = ohlcv[:-1]
    highs = [c['h'] for c in closed_ohlcv]
    lows = [c['l'] for c in closed_ohlcv]
    closes = [c['c'] for c in closed_ohlcv]
    atr = compute_atr(highs, lows, closes)

    obs = []

    # 1. Identify OBs in history
    for i in range(1, len(closed_ohlcv) - 1):
        prev = closed_ohlcv[i-1]
        curr = closed_ohlcv[i]
        nxt = closed_ohlcv[i+1]

        if curr['c'] < curr['o']: # Bearish candle
            impulse_range = nxt['h'] - nxt['l']
            if impulse_range > IMPULSE_MULT * atr and nxt['c'] > curr['h']:
                obs.append({
                    'type': 'bullish',
                    'top': curr['h'],
                    'bottom': curr['l'],
                    'index': i,
                    'state': 'active'
                })
        elif curr['c'] > curr['o']: # Bullish candle
            impulse_range = nxt['h'] - nxt['l']
            if impulse_range > IMPULSE_MULT * atr and nxt['c'] < curr['l']:
                obs.append({
                    'type': 'bearish',
                    'top': curr['h'],
                    'bottom': curr['l'],
                    'index': i,
                    'state': 'active'
                })

    if not obs:
        return {'ob_count': 0, 'nearest_ob': None}

    # 2. Update states using live data
    last_candle = ohlcv[-1]

    for ob in obs:
        post_ob_candles = ohlcv[ob['index']+2:]
        for pc in post_ob_candles:
            if ob['type'] == 'bullish' and pc['c'] < ob['bottom'] * (1 - INVALIDATION_MARGIN):
                ob['state'] = 'breaker'
            elif ob['type'] == 'bearish' and pc['c'] > ob['top'] * (1 + INVALIDATION_MARGIN):
                ob['state'] = 'breaker'
            elif pc['h'] >= ob['bottom'] and pc['l'] <= ob['top']:
                if ob['state'] == 'active':
                    ob['state'] = 'mitigated'

    active_obs = [ob for ob in obs if ob['state'] == 'active']
    breakers = [ob for ob in obs if ob['state'] == 'breaker']

    return {
        'ob_active_count': len(active_obs),
        'breaker_count': len(breakers),
        'nearest_ob_type': active_obs[-1]['type'] if active_obs else None,
        'has_breaker': len(breakers) > 0
    }
