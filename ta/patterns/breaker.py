"""
Breaker Block (Breaker) Identification Module

How it works:
1. This module identifies "Breaker Blocks"—which are failed Order Blocks
   that have flipped polarity.
2. A Bullish Breaker is a failed bearish Order Block. When price closes
   above the top of a Bearish OB, that block flips polarity to become
   a source of future demand (Bullish Breaker).
3. A Bearish Breaker is a failed bullish Order Block. When price closes
   below the bottom of a Bullish OB, that block flips polarity to become
   a source of future supply (Bearish Breaker).
4. Retests / Mitigation: Once a breaker forms, it can be mitigated/filled
   if subsequent candles wick into its range.
"""

from typing import List, Dict, Optional, Any
import math
from ta.patterns.ob import compute_atr_series

# Standard impulse candle multiplier (matching ob.py).
IMPULSE_MULT = 1.5

# Margin (%) required to invalidate an OB and turn it into a Breaker.
INVALIDATION_MARGIN = 0.001

def detect_breakers(
    ohlcv: List[dict],
    period: int = 14,
    invalidation_margin: Optional[float] = None,
    impulse_mult: Optional[float] = None,
    closed_only: bool = False,
    enabled: bool = True
) -> Dict[str, Any]:
    """
    Identifies active (unmitigated) and historical breaker blocks.
    Evaluates signals strictly using closed candles to prevent look-ahead bias and repainting.
    Judges historic candles against contemporary ATR series.

    NOTE: Always use 'ts' as the unique identifier/dedupe key for breakers.
    """
    if invalidation_margin is None:
        invalidation_margin = INVALIDATION_MARGIN
    if impulse_mult is None:
        impulse_mult = IMPULSE_MULT

    if period <= 0:
        raise ValueError(f"Period must be greater than 0, got {period}")

    if impulse_mult <= 0.0:
        raise ValueError(f"impulse_mult must be greater than 0, got {impulse_mult}")

    # Chronological & Schema validation to fail loudly on malformed/NaN/Infinity inputs [REPAIR]
    for idx, c in enumerate(ohlcv):
        if not all(k in c for k in ('ts', 'o', 'h', 'l', 'c')):
            raise ValueError(f"Candle at index {idx} is missing required OHLCV keys: {c}")
        if idx > 0 and c['ts'] <= ohlcv[idx-1]['ts']:
            raise ValueError(f"Candles are not in chronological order: index {idx} ts {c['ts']} <= index {idx-1} ts {ohlcv[idx-1]['ts']}")

        # Type & Numeric Bounds validation [REPAIR]
        for k in ('o', 'h', 'l', 'c'):
            val = c[k]
            if not isinstance(val, (int, float)):
                raise ValueError(f"Candle at index {idx} has non-numeric type for '{k}': {val} ({type(val)})")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"Candle at index {idx} has invalid NaN or Infinity value for '{k}': {val}")

        # Check for physically impossible candles (such as high < low, or open/close outside high/low) [REPAIR]
        is_invalid = (
            c['o'] < c['l'] or c['o'] > c['h'] or
            c['c'] < c['l'] or c['c'] > c['h'] or
            c['h'] < c['l']
        )
        if is_invalid:
            raise ValueError(f"Candle at index {idx} has inconsistent OHLC values: {c}")

    # Decouple warmup entirely from array length using a stable, scaled floor [REPAIR-001]
    warmup_bars = period + (4 * period)

    if not enabled or len(ohlcv) < (warmup_bars + 3):
        return {
            'breaker_count': 0,
            'nearest_breaker_type': None,
            'latest_breaker_type': None,
            'breakers': [],
            'all_breakers': []
        }

    # Support closed_only to prevent positional look-ahead assumptions [REPAIR-002]
    closed_ohlcv = ohlcv if closed_only else ohlcv[:-1]
    highs = [c['h'] for c in closed_ohlcv]
    lows = [c['l'] for c in closed_ohlcv]
    closes = [c['c'] for c in closed_ohlcv]

    # Compute rolling ATR series to prevent historical drift/repainting [REPAIR-001]
    atr_series = compute_atr_series(highs, lows, closes, period)

    obs = []

    # 1. Identify Candidate OBs in history
    for i in range(1, len(closed_ohlcv) - 1):
        # Only discover/report OBs formed AFTER the stable, converged warmup period
        if i < warmup_bars:
            continue

        curr = closed_ohlcv[i]
        nxt = closed_ohlcv[i+1]
        atr_val = atr_series[i]

        if atr_val <= 0.0:
            continue

        impulse_range = nxt['h'] - nxt['l']
        is_impulsive = impulse_range > (impulse_mult * atr_val)

        # Doji Hardening: treat small body relative to range (within 10% tolerance) as doji [REPAIR]
        candle_range = curr['h'] - curr['l']
        is_doji = abs(curr['c'] - curr['o']) <= (candle_range * 0.1) if candle_range > 0.0 else True
        is_bearish_or_ambiguous = curr['c'] < curr['o'] or (is_doji and nxt['c'] > curr['h'])
        is_bullish_or_ambiguous = curr['c'] > curr['o'] or (is_doji and nxt['c'] < curr['l'])

        # Sweep-through Check on Creation [REPAIR-001]
        is_swept = (is_bearish_or_ambiguous and nxt['l'] < curr['l']) or (is_bullish_or_ambiguous and nxt['h'] > curr['h'])
        ob_state = 'mitigated' if is_swept else 'active'

        if is_bearish_or_ambiguous and is_impulsive and nxt['c'] > curr['h']:
            obs.append({
                'type': 'bullish',  # Originally a Bullish OB
                'top': curr['h'],
                'bottom': curr['l'],
                'index': i,
                'state': ob_state,
                'ts': curr['ts']
            })
        elif is_bullish_or_ambiguous and is_impulsive and nxt['c'] < curr['l']:
            obs.append({
                'type': 'bearish',  # Originally a Bearish OB
                'top': curr['h'],
                'bottom': curr['l'],
                'index': i,
                'state': ob_state,
                'ts': curr['ts']
            })

    breakers = []

    # 2. Check for invalidations (breaks) to identify Breaker Blocks
    for ob in obs:
        post_ob_candles = closed_ohlcv[ob['index']+2:]
        for idx, pc in enumerate(post_ob_candles):
            is_broken = False
            breaker_type = None

            if ob['type'] == 'bullish' and pc['c'] < ob['bottom'] * (1 - invalidation_margin):
                # Bullish OB fails and becomes a Bearish Breaker
                is_broken = True
                breaker_type = 'bearish'
            elif ob['type'] == 'bearish' and pc['c'] > ob['top'] * (1 + invalidation_margin):
                # Bearish OB fails and becomes a Bullish Breaker
                is_broken = True
                breaker_type = 'bullish'

            if is_broken:
                # The index/timestamp where the break occurred
                breaker_formation_idx = ob['index'] + 2 + idx
                breakers.append({
                    'type': breaker_type,
                    'top': ob['top'],
                    'bottom': ob['bottom'],
                    'index': breaker_formation_idx,
                    'ts': pc['ts'],
                    'state': 'active'
                })
                break  # This block is now permanently a Breaker, stop scanning for break

    # 3. Check for mitigation of Breaker Blocks by subsequent candles up to the current live candle
    for br in breakers:
        # NOTE: Mitigation intentionally scans subsequent candles including the live candle,
        # which is 100% safe because a live candle's high/low can only expand during formation.
        post_breaker_candles = ohlcv[br['index']+1:]
        for pc in post_breaker_candles:
            if pc['l'] <= br['top'] and pc['h'] >= br['bottom']:
                br['state'] = 'mitigated'
                break

    active_breakers = [br for br in breakers if br['state'] == 'active']
    latest_breaker_type = active_breakers[-1]['type'] if active_breakers else None

    return {
        'breaker_count': len(active_breakers),
        'latest_breaker_type': latest_breaker_type,
        'nearest_breaker_type': latest_breaker_type,  # Legacy alias
        'breakers': active_breakers,
        'all_breakers': breakers
    }
