"""
> ta/candles/sentiment.py

1. Summary: Stateless pattern recognizer analyzing body location inside candle range.
2. Description: Classifies candle sentiment based on whether the candle body is located in the top, bottom, or middle of the full range.
3. Context: Utilized by candle patterns analysis and indicators features pipeline.

Audited by Claude on 7/31/2026
"""

from typing import Dict, List, Optional

from tools.trading_utils import calculate_tp_for_roe

# --- Defaults (used when the corresponding optional param isn't supplied) ---
DEFAULT_LEEWAY = 1.0  # +/- percentage points allowed when matching target_body_pct / target_offset_pct
DEFAULT_TARGET_ROE = 0.01
DEFAULT_LEVERAGE = 20  # Mirrors the maxLever fallback in tools/trading_utils.format_order_quantity
SL_TICK_BUFFER = 0.0001  # 0.01% proxy, not exposed as a param


def _within_leeway(value: float, target: float, leeway: float) -> bool:
    return (target - leeway) <= value <= (target + leeway)


def _parse_optional_float(params: List, index: int, default: float) -> Optional[float]:
    """
    Returns float(params[index]) if that slot was supplied, else `default`.
    Returns None (an "invalid" sentinel, never a legitimate value here since
    none of the defaults are None) if the slot was supplied but isn't parseable.
    """
    if len(params) <= index:
        return default
    try:
        return float(params[index])
    except (TypeError, ValueError):
        return None


def _build_signal(side: str, entry: float, stop: float, body_pct: float, offset_pct: float,
                   target_roe: float, leverage: float) -> Dict:
    tp = calculate_tp_for_roe(entry, target_roe, side, leverage, entry_maker=False, exit_maker=True)
    return {
        "side": side,
        "entry_price": entry,
        "stop_price": stop,
        "exit_price": tp,
        "metadata": {
            "type": "body_location",
            "body_pct": body_pct,
            "offset_pct": offset_pct,
            "target_roe": target_roe,
            "leverage": leverage,
        },
    }


def get_signal(ohlcv: List[Dict[str, float]], tf: str, params: Optional[List] = None, **kwargs) -> Optional[Dict]:
    """
    Matches the current candle's body size and edge offset against target percentages.

    Args:
        ohlcv: Candle dicts with at least {o, h, l, c}. Only ohlcv[-1] is examined --
            this pattern is single-candle and stateless.
        tf: Timeframe string (e.g. '5m'). Accepted for ta/strategy_interface.py
            compatibility; unused by this pattern.
        params: [target_body_pct, target_offset_pct, leeway, target_roe, leverage].
            - target_body_pct, target_offset_pct: required.
            - leeway, target_roe, leverage: optional; fall back to DEFAULT_LEEWAY,
              DEFAULT_TARGET_ROE, DEFAULT_LEVERAGE when not supplied.
            All five are coerced to float. A slot that IS supplied but isn't a valid
            float invalidates the whole call (same treatment as target_body_pct /
            target_offset_pct), rather than silently falling back to its default --
            only an *absent* slot uses the default. leverage must also be positive
            (calculate_tp_for_roe divides by it, so 0 or negative is rejected).
            Extra elements past index 4 are ignored.
        **kwargs: Unused; accepted for interface compatibility.

    Returns:
        A signal dict (see ta/strategy_interface.py) if the body occupies target_body_pct
        of the range AND sits within target_offset_pct of the high (bullish/buy) or low
        (bearish/sell) edge. None if there's no match or the inputs are unusable. If both
        edges independently match, buy takes priority -- same order as the original.
    """
    if not params or len(params) < 2:
        return None

    try:
        target_body_pct = float(params[0])
        target_offset_pct = float(params[1])
    except (TypeError, ValueError):
        return None

    leeway = _parse_optional_float(params, 2, DEFAULT_LEEWAY)
    target_roe = _parse_optional_float(params, 3, DEFAULT_TARGET_ROE)
    leverage = _parse_optional_float(params, 4, DEFAULT_LEVERAGE)

    if leeway is None or target_roe is None or leverage is None or leverage <= 0:
        return None

    if not ohlcv:
        return None

    curr = ohlcv[-1]
    high, low = curr['h'], curr['l']
    open_p, close_p = curr['o'], curr['c']
    range_p = high - low

    if range_p <= 0:
        return None

    body_max = max(open_p, close_p)
    body_min = min(open_p, close_p)
    body_pct = ((body_max - body_min) / range_p) * 100

    if not _within_leeway(body_pct, target_body_pct, leeway):
        return None

    # Bullish: top of body near the high
    bullish_offset = ((high - body_max) / range_p) * 100
    if _within_leeway(bullish_offset, target_offset_pct, leeway):
        return _build_signal(
            side="buy",
            entry=close_p,
            stop=low * (1 - SL_TICK_BUFFER),
            body_pct=body_pct,
            offset_pct=bullish_offset,
            target_roe=target_roe,
            leverage=leverage,
        )

    # Bearish: bottom of body near the low
    bearish_offset = ((body_min - low) / range_p) * 100
    if _within_leeway(bearish_offset, target_offset_pct, leeway):
        return _build_signal(
            side="sell",
            entry=close_p,
            stop=high * (1 + SL_TICK_BUFFER),
            body_pct=body_pct,
            offset_pct=bearish_offset,
            target_roe=target_roe,
            leverage=leverage,
        )

    return None
