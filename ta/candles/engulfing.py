"""
> ta/candles/engulfing.py

1. Summary: Stateless pattern recognizer for engulfing candles, covering
   both body-only and full-range (total) variants via a single parameter.
2. Description: Identifies engulfing candlestick patterns: the current
   candle's body fully covers a comparison range on the previous candle,
   after a red<->green reversal between the two candles.
   params={"scope": "body"} (default) compares against the previous
   candle's body (open/close) only; params={"scope": "total"} compares
   against its entire range (high/low, wicks included). These were
   originally two separate files (engulfing.py and engulfing_total.py);
   merged 2026-07-31 once [CANDLES-005]'s reversal-requirement fix
   confirmed the only remaining difference between them was this one
   comparison range -- see [CANDLES-006] below. This module performs
   analysis only -- it does not compute entry/stop/exit prices and has no
   knowledge of order types, fees, or leverage. Constructing a trade from
   this pattern's output is strategy-layer work, entirely outside this
   module.
3. Context: Utilized by candle patterns analysis. Implements the
   detect(ohlcv, timeframe, params, **kwargs) contract defined in
   ta/strategy_interface.py. Overlap logic shared via ta/helpers/overlap.py;
   both the scope and strict_overlap toggles resolved via
   ta/helpers/params.py.

[CANDLES-006, merged 2026-07-31] ta/candles/engulfing_total.py has been
folded into this file and deleted. Its logic differed from this file's
only in which previous-candle range gets compared (body vs. full
high/low), now controlled by params["scope"]. Nothing in strategies/
referenced ta/candles/engulfing_total.py directly (confirmed by grep), so
no call sites needed updating -- but if that changes before anyone reads
this, the fix is: import ta.candles.engulfing instead and pass
params={"scope": "total"} to get the old engulfing_total.py behavior.
Output metadata["type"] still distinguishes the two patterns
("body_engulfing" vs "total_engulfing"), unchanged from when they were
separate files.

Audited by Claude on 7/31/2026
"""

from typing import Dict, List, Optional

from ta.helpers.overlap import range_covers
from ta.helpers.params import resolve

PATTERN_TYPES = {
    "body": "body_engulfing",
    "total": "total_engulfing",
}


def detect(
    ohlcv: List[Dict[str, float]],
    timeframe: str,
    params: Optional[Dict] = None,
    **kwargs,
) -> Optional[Dict]:
    """
    Detect an engulfing pattern: the current candle's body fully covers a
    comparison range on the previous candle, and the two candles are
    opposite colors (a red candle followed by a covering green one, or
    vice versa).

    params={"scope": "body"} (default): compares against the previous
    candle's body (open/close) only -- the original engulfing.py behavior.
    params={"scope": "total"}: compares against the previous candle's
    entire range (high/low, wicks included) -- the original
    engulfing_total.py behavior, now folded into this file.

    By default the overlap test is inclusive; pass
    params={"strict_overlap": True} to require the current body to
    strictly exceed the comparison range's edges instead of just meeting
    them. Independent of `scope` -- the two can be combined freely.

    Args:
        ohlcv: Sequence of bars, each a dict with at least 'o', 'c' for
            both bars. For scope="total", the previous bar additionally
            needs 'h', 'l'. Only the last two bars are inspected; a
            missing key raises KeyError rather than failing silently.
        timeframe: Timeframe string for the candles. Unused by this
            pattern's own logic; kept to match ta/strategy_interface.py's
            contract and the shared call signature across ta/candles/*.
        params: Optional per-call overrides, dict-style (`.get(key, ...)`).
            [HELPERS-001, see ta/helpers/params.py] this shape is a working
            assumption, not a confirmed one. Recognized keys:
              - scope ("body" | "total"): which previous-candle range to
                compare against. Default "body". Any other value raises
                ValueError -- an unrecognized scope is a caller mistake,
                not "no pattern found", so it's not swallowed into a
                silent None.
              - strict_overlap (bool): require strict containment rather
                than inclusive. Default False.
        **kwargs: Not part of the named interface; accepted for
            forward-compatible call signatures.

    Returns:
        {"side": "buy" | "sell", "metadata": {"type": "body_engulfing" |
        "total_engulfing"}} if a pattern is found on the latest bar, else
        None. Deliberately excludes entry/stop/exit prices and anything
        order-type or fee related -- see ta/strategy_interface.py.

    Raises:
        ValueError: if params["scope"] is present but not "body" or
            "total".
    """
    if len(ohlcv) < 2:
        return None

    params = params or {}
    strict = resolve(params, "strict_overlap", False)
    scope = resolve(params, "scope", "body")
    if scope not in PATTERN_TYPES:
        raise ValueError(f"engulfing scope must be one of {sorted(PATTERN_TYPES)}, got {scope!r}")

    prev, curr = ohlcv[-2], ohlcv[-1]
    prev_open, prev_close = prev["o"], prev["c"]
    curr_open, curr_close = curr["o"], curr["c"]

    curr_body_low, curr_body_high = min(curr_open, curr_close), max(curr_open, curr_close)
    if scope == "total":
        prev_range_low, prev_range_high = prev["l"], prev["h"]
    else:
        prev_range_low, prev_range_high = min(prev_open, prev_close), max(prev_open, prev_close)

    engulfed = range_covers(curr_body_low, curr_body_high, prev_range_low, prev_range_high, strict=strict)

    is_bullish = curr_close > curr_open and prev_open > prev_close and engulfed
    is_bearish = curr_close < curr_open and prev_open < prev_close and engulfed

    if not (is_bullish or is_bearish):
        return None

    return {
        "side": "buy" if is_bullish else "sell",
        "metadata": {"type": PATTERN_TYPES[scope]},
    }
