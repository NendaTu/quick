"""
1. Summary: Stateless Order Block (OB) identification module.
2. Description: Locates institutional buying/selling block areas with ATR-based warmup and mitigation checks.
3. Context: Crucial stateless pattern-discovery module used by Agt levelFinder strategies.
"""
from typing import List, Dict, Optional, Any
import math

# Impulse candle range must be > IMPULSE_MULT * ATR.
IMPULSE_MULT = 1.5

def compute_atr_series(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """
    Computes a full series of ATR values matching the length of the input lists.
    Each element i represents the ATR at that index, calculated using data up to index i.
    Uses Wilder's Smoothing for stable volatility estimation.
    """
    if period <= 0:
        raise ValueError(f"Period must be greater than 0, got {period}")

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
    closed_only: bool = False,
    enabled: bool = True
) -> Dict[str, Any]:
    """
    Identifies active (unfilled/unmitigated) and historical order blocks.
    Evaluates signals strictly using closed candles to prevent look-ahead bias and repainting.
    Judges historic candles against the contemporary ATR value at that point in time.

    NOTE: The 'index' field of returning order blocks is relative to the input array
    and can change if the history window is sliced or shifted. Always use 'ts' as
    the unique identifier/dedupe key.

    NOTE: 'latest_ob_type' refers to the most recently formed active OB, not price distance.

    NOTE: Wilder's smoothed ATR calculation is path-dependent from the first candle.
    To ensure identical outputs and avoid sliding-window path-dependency, callers must
    always provide a fixed-origin growing list of candles, or ensure the history window size
    is sufficiently large (at least 5x period beyond the warmup floor).
    """
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

    # The loop below needs len(closed_ohlcv) >= warmup_bars + 2 to ever reach i=warmup_bars.
    # closed_ohlcv is ohlcv itself when closed_only=True, or ohlcv[:-1] otherwise, so the
    # required length on the raw `ohlcv` input differs by one between the two modes.
    implied_closed_len = len(ohlcv) if closed_only else len(ohlcv) - 1
    if not enabled or implied_closed_len < (warmup_bars + 2):
        return {
            'ob_active_count': 0,
            'latest_ob_type': None,
            'nearest_ob_type': None,  # Legacy alias for latest_ob_type (recency, not price distance)
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

    obs = []

    # 1. Identify OBs in history
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

        # Doji Hardening: treat small body relative to range (within 10% tolerance) as doji / ambiguous [REPAIR]
        candle_range = curr['h'] - curr['l']
        is_doji = abs(curr['c'] - curr['o']) <= (candle_range * 0.1) if candle_range > 0.0 else True
        is_bearish_or_ambiguous = curr['c'] < curr['o'] or (is_doji and nxt['c'] > curr['h'])
        is_bullish_or_ambiguous = curr['c'] > curr['o'] or (is_doji and nxt['c'] < curr['l'])

        # Sweep-through Check on Creation [REPAIR-001]
        # Avoids reporting order blocks where the impulse candle already swept past the zone
        # bottom (Bullish OB) or top (Bearish OB) during formation.
        #
        # IMPORTANT: this must be evaluated AFTER we know which OB type is actually forming,
        # using only that direction's check. is_bearish_or_ambiguous and is_bullish_or_ambiguous
        # are NOT mutually exclusive (a doji whose tiny body leans one way still sets both flags),
        # so combining both checks with OR up front -- gated on the ambiguous flags rather than on
        # which branch fires -- lets the *other* direction's check leak in. That other check then
        # collapses to something already implied by the break condition itself (nxt['h'] > curr['h']
        # is guaranteed whenever nxt['c'] > curr['h']), so it would fire on every doji-originated
        # bullish OB whose tiny body happened to close green, marking clean, unswept OBs as
        # mitigated on creation. Computing it per-branch avoids that entirely.

        if is_bearish_or_ambiguous and is_impulsive and nxt['c'] > curr['h']:
            is_swept = nxt['l'] < curr['l']
            obs.append({
                'type': 'bullish',
                'top': curr['h'],
                'bottom': curr['l'],
                'index': i,
                'state': 'mitigated' if is_swept else 'active',
                'ts': curr['ts']
            })
        elif is_bullish_or_ambiguous and is_impulsive and nxt['c'] < curr['l']:
            is_swept = nxt['h'] > curr['h']
            obs.append({
                'type': 'bearish',
                'top': curr['h'],
                'bottom': curr['l'],
                'index': i,
                'state': 'mitigated' if is_swept else 'active',
                'ts': curr['ts']
            })

    # 2. Update states (mitigation) based on subsequent candles up to the current live candle.
    # NOTE: Mitigation intentionally scans subsequent candles including the live candle,
    # which is 100% safe because a live candle's high/low can only expand during formation.
    # A single forward pass is used instead of re-scanning the remaining array once per OB:
    # each candle is checked only against OBs still unresolved at that point, and OBs already
    # mitigated at creation (via the sweep-through check) are never tracked at all. This is a
    # meaningful speedup whenever OBs tend to get mitigated within a bounded number of bars, as
    # in ordinary oscillating price action -- it is NOT a fix to the theoretical worst case: a
    # history with many OBs that all stay simultaneously active for a very long stretch is still
    # O(N^2) here, since every live candle must be checked against every still-open zone. A
    # genuine worst-case fix (e.g. an interval tree / sweep-line over price levels) would be a
    # larger change; flag it separately if profiling ever shows this loop as an actual bottleneck.
    obs_ready_at = {}
    for ob in obs:
        if ob['state'] == 'active':  # already-mitigated-on-formation OBs need no further scanning
            obs_ready_at.setdefault(ob['index'] + 2, []).append(ob)

    still_unmitigated = []
    for idx, pc in enumerate(ohlcv):
        if idx in obs_ready_at:
            still_unmitigated.extend(obs_ready_at[idx])
        if not still_unmitigated:
            continue
        remaining = []
        for ob in still_unmitigated:
            if pc['l'] <= ob['top'] and pc['h'] >= ob['bottom']:
                ob['state'] = 'mitigated'
            else:
                remaining.append(ob)
        still_unmitigated = remaining

    active_obs = [ob for ob in obs if ob['state'] == 'active']
    latest_ob_type = active_obs[-1]['type'] if active_obs else None

    return {
        'ob_active_count': len(active_obs),
        'latest_ob_type': latest_ob_type,
        'nearest_ob_type': latest_ob_type,  # Legacy alias for latest_ob_type ONLY. Despite the
                                             # name, this is recency (most recently formed), NOT
                                             # proximity in price -- this function has no current
                                             # price input, so a true nearest-by-price value isn't
                                             # computable here. Callers wanting real price-distance
                                             # nearness must derive it themselves from active_obs.
        'active_obs': active_obs,
        'all_obs': obs
    }
