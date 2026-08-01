"""
> ta/candles/engulfing.py

1. Summary: Stateless pattern recognizer for body-only engulfing candles.
2. Description: Identifies engulfing candlestick patterns where only the
   candle body overlaps the previous bar's body; wicks play no part in
   detection. This module performs analysis only -- it does not compute
   entry/stop/exit prices and has no knowledge of order types, fees, or
   leverage. Constructing a trade from this pattern's output is
   strategy-layer work, entirely outside this module.
3. Context: Utilized by candle patterns analysis. Implements the
   detect(ohlcv, timeframe, params, **kwargs) contract defined in
   ta/strategy_interface.py. Overlap logic shared via ta/helpers/overlap.py;
   the strict_overlap toggle resolved via ta/helpers/params.py.

Audited by Claude on 7/31/2026
"""

from typing import Dict, List, Optional

from ta.helpers.overlap import range_covers
from ta.helpers.params import resolve

PATTERN_TYPE = "body_engulfing"


def detect(
    ohlcv: List[Dict[str, float]],
    timeframe: str,
    params: Optional[Dict] = None,
    **kwargs,
) -> Optional[Dict]:
    """
    Detect a body-only bullish or bearish engulfing pattern on the last two bars.

    A pattern is found when the current candle's body fully covers the
    previous candle's body (open/close only; wicks play no part). By
    default the overlap test is inclusive, matching this pattern's original
    behavior; pass params={"strict_overlap": True} to require the current
    body to strictly exceed the previous body's edges instead of just
    meeting them.

    Args:
        ohlcv: Sequence of bars, each a dict with at least 'o', 'c'. Only
            the last two bars are inspected; a missing key on either raises
            KeyError rather than failing silently.
        timeframe: Timeframe string for the candles. Unused by this
            pattern's own logic; kept to match ta/strategy_interface.py's
            contract and the shared call signature across ta/candles/*.
        params: Optional per-call overrides, dict-style (`.get(key, ...)`).
            [HELPERS-001, see ta/helpers/params.py] this shape is a working
            assumption, not a confirmed one. Recognized keys:
              - strict_overlap (bool): require strict containment rather
                than inclusive. Default False (original behavior).
        **kwargs: Not part of the named interface; accepted for
            forward-compatible call signatures.

    Returns:
        {"side": "buy" | "sell", "metadata": {"type": "body_engulfing"}}
        if a pattern is found on the latest bar, else None. Deliberately
        excludes entry/stop/exit prices and anything order-type or fee
        related -- see ta/strategy_interface.py.
    """
    if len(ohlcv) < 2:
        return None

    params = params or {}
    strict = resolve(params, "strict_overlap", False)

    prev, curr = ohlcv[-2], ohlcv[-1]
    prev_open, prev_close = prev["o"], prev["c"]
    curr_open, curr_close = curr["o"], curr["c"]

    curr_body_low, curr_body_high = min(curr_open, curr_close), max(curr_open, curr_close)
    prev_body_low, prev_body_high = min(prev_open, prev_close), max(prev_open, prev_close)
    body_engulfed = range_covers(
        curr_body_low, curr_body_high, prev_body_low, prev_body_high, strict=strict
    )

    is_bullish = curr_close > curr_open and prev_open > prev_close and body_engulfed
    is_bearish = curr_close < curr_open and prev_open < prev_close and body_engulfed

    if not (is_bullish or is_bearish):
        return None

    return {
        "side": "buy" if is_bullish else "sell",
        "metadata": {"type": PATTERN_TYPE},
    }
