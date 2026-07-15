"""
Order Block (OB) Identification Module

How it works:
1. This module identifies "Order Blocks"—price zones where institutional
   buying or selling occurred before a strong, fast move.
2. A Bullish OB is a bearish candle followed by a rapid upward "impulse"
   that breaks its high.
3. A Bearish OB is a bullish candle followed by a rapid downward "impulse"
   that breaks its low.
4. This file is stateless, strictly focused on technical analysis discovery,
   and does not contain entries, exits, stops, or signal triggers.
"""

from typing import List, Dict, Optional

# --- Configuration ---
# Toggle to enable/disable Order Block detection.
ENABLED = True

# Impulse candle range must be > IMPULSE_MULT * ATR.
IMPULSE_MULT = 1.5

def compute_atr_series(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """
    Computes a full series of ATR values matching the length of the input lists.
    Each element i represents the ATR at that index, calculated using data up to index i.
    Uses Wilder's Smoothing for stable volatility estimation.
    """
    atr_series = [0.0] * len(closes)
    if len(closes) < period + 1:
        return atr_series

    # 1. Calculate True Ranges
    tr_series = [0.0]  # First element is 0 as we need previous close
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        tr_series.append(tr)

    # 2. Initial Seed (SMA) at index `period`
    initial_tr_sum = sum(tr_series[1:period + 1])
    atr = initial_tr_sum / period
    atr_series[period] = atr

    # 3. Recursive Smoothing (Wilder's)
    for i in range(period + 1, len(closes)):
        tr = tr_series[i]
        atr = (atr * (period - 1) + tr) / period
        atr_series[i] = atr

    # Backfill pre-period values with the initial seed to avoid 0.0 values
    for i in range(1, period):
        atr_series[i] = atr_series[period]

    return atr_series

def detect_order_blocks(ohlcv: List[dict], period: int = 14, impulse_mult: float = IMPULSE_MULT) -> Dict:
    """
    Identifies active (unfilled/unmitigated) and historical order blocks.
    Evaluates signals strictly using closed candles to prevent look-ahead bias and repainting.
    Judges historic candles against the contemporary ATR value at that point in time.
    """
    if not ENABLED or len(ohlcv) < period + 3:
        return {
            'ob_active_count': 0,
            'nearest_ob_type': None,
            'active_obs': [],
            'all_obs': []
        }

    # Evaluate using closed candles only to prevent repainting
    closed_ohlcv = ohlcv[:-1]
    highs = [c['h'] for c in closed_ohlcv]
    lows = [c['l'] for c in closed_ohlcv]
    closes = [c['c'] for c in closed_ohlcv]

    # Compute rolling ATR series to prevent historical drift/repainting [REPAIR-001]
    atr_series = compute_atr_series(highs, lows, closes, period)

    obs = []

    # 1. Identify OBs in history
    for i in range(1, len(closed_ohlcv) - 1):
        curr = closed_ohlcv[i]
        nxt = closed_ohlcv[i+1]
        atr_val = atr_series[i]

        if atr_val <= 0.0:
            continue

        impulse_range = nxt['h'] - nxt['l']
        is_impulsive = impulse_range > (impulse_mult * atr_val)

        # Doji Hardening: treat open == close as bearish/bullish based on next direction
        is_bearish = curr['c'] < curr['o'] or (curr['c'] == curr['o'] and nxt['c'] > curr['h'])
        is_bullish = curr['c'] > curr['o'] or (curr['c'] == curr['o'] and nxt['c'] < curr['l'])

        if is_bearish and is_impulsive and nxt['c'] > curr['h']:
            obs.append({
                'type': 'bullish',
                'top': curr['h'],
                'bottom': curr['l'],
                'index': i,
                'state': 'active',
                'ts': curr['ts']
            })
        elif is_bullish and is_impulsive and nxt['c'] < curr['l']:
            obs.append({
                'type': 'bearish',
                'top': curr['h'],
                'bottom': curr['l'],
                'index': i,
                'state': 'active',
                'ts': curr['ts']
            })

    # 2. Update states (mitigation) based on subsequent candles up to the current live candle
    # Mitigate if any subsequent candle high/low intersects the OB range
    for ob in obs:
        post_ob_candles = ohlcv[ob['index']+2:]
        for pc in post_ob_candles:
            if pc['l'] <= ob['top'] and pc['h'] >= ob['bottom']:
                ob['state'] = 'mitigated'
                break

    active_obs = [ob for ob in obs if ob['state'] == 'active']

    return {
        'ob_active_count': len(active_obs),
        'nearest_ob_type': active_obs[-1]['type'] if active_obs else None,
        'active_obs': active_obs,
        'all_obs': obs
    }
