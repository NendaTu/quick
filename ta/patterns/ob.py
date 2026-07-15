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

from typing import List, Dict, Optional, Any

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

    return atr_series

def detect_order_blocks(
    ohlcv: List[dict],
    period: int = 14,
    impulse_mult: Optional[float] = None,
    closed_only: bool = False
) -> Dict[str, Any]:
    """
    Identifies active (unfilled/unmitigated) and historical order blocks.
    Evaluates signals strictly using closed candles to prevent look-ahead bias and repainting.
    Judges historic candles against the contemporary ATR value at that point in time.

    NOTE: The 'index' field of returning order blocks is relative to the input array
    and can change if the history window is sliced or shifted. Always use 'ts' as
    the unique identifier/dedupe key.

    NOTE: 'latest_ob_type' refers to the most recently formed active OB, not price distance.
    """
    if impulse_mult is None:
        impulse_mult = IMPULSE_MULT

    if period <= 0:
        raise ValueError(f"Period must be greater than 0, got {period}")

    # Chronological & Schema validation to fail loudly on malformed inputs [REPAIR]
    for idx, c in enumerate(ohlcv):
        if not all(k in c for k in ('ts', 'o', 'h', 'l', 'c')):
            raise ValueError(f"Candle at index {idx} is missing required OHLCV keys: {c}")
        if idx > 0 and c['ts'] <= ohlcv[idx-1]['ts']:
            raise ValueError(f"Candles are not in chronological order: index {idx} ts {c['ts']} <= index {idx-1} ts {ohlcv[idx-1]['ts']}")

    if not ENABLED or len(ohlcv) < period + 3:
        return {
            'ob_active_count': 0,
            'latest_ob_type': None,
            'nearest_ob_type': None,  # Legacy alias
            'active_obs': [],
            'all_obs': []
        }

    # Support closed_only to prevent positional look-ahead assumptions [REPAIR-002]
    closed_ohlcv = ohlcv if closed_only else ohlcv[:-1]
    highs = [c['h'] for c in closed_ohlcv]
    lows = [c['l'] for c in closed_ohlcv]
    closes = [c['c'] for c in closed_ohlcv]

    # Compute rolling ATR series to prevent historical drift/repainting [REPAIR-001]
    atr_series = compute_atr_series(highs, lows, closes, period)

    # Converge Wilder's smoothed ATR by enforcing dynamic warmup pruning [REPAIR-001]
    # This prevents early SMA seed values from triggering different results on sliding windows.
    warmup_bars = min(len(closed_ohlcv) // 3, period + 50)

    obs = []

    # 1. Identify OBs in history
    for i in range(1, len(closed_ohlcv) - 1):
        # Only discover/report OBs formed AFTER the converged warmup buffer period
        if i < warmup_bars:
            continue

        curr = closed_ohlcv[i]
        nxt = closed_ohlcv[i+1]
        atr_val = atr_series[i]

        if atr_val <= 0.0:
            continue

        impulse_range = nxt['h'] - nxt['l']
        is_impulsive = impulse_range > (impulse_mult * atr_val)

        # Doji Hardening: treat open == close (within relative epsilon) as bearish/bullish based on next direction
        is_doji = abs(curr['c'] - curr['o']) < (curr['o'] * 1e-5)
        is_bearish = curr['c'] < curr['o'] or (is_doji and nxt['c'] > curr['h'])
        is_bullish = curr['c'] > curr['o'] or (is_doji and nxt['c'] < curr['l'])

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
    for ob in obs:
        post_ob_candles = ohlcv[ob['index']+2:]
        for pc in post_ob_candles:
            if pc['l'] <= ob['top'] and pc['h'] >= ob['bottom']:
                ob['state'] = 'mitigated'
                break

    active_obs = [ob for ob in obs if ob['state'] == 'active']
    latest_ob_type = active_obs[-1]['type'] if active_obs else None

    return {
        'ob_active_count': len(active_obs),
        'latest_ob_type': latest_ob_type,
        'nearest_ob_type': latest_ob_type,  # Legacy alias for backward compatibility
        'active_obs': active_obs,
        'all_obs': obs
    }
