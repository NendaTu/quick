"""
> ta/helpers/overlap.py

1. Summary: Single-concern range-containment check shared by candle
   body/range overlap patterns.
2. Description: A single "does the outer range fully contain the inner
   range" comparison. ta/candles/engulfing.py's body-vs-body check and
   ta/candles/engulfing_total.py's body-vs-full-range check both reduce to
   this same comparison with different inputs -- extracted once here rather
   than duplicated per pattern.
3. Context: Introduced alongside ta/helpers/params.py while de-duplicating
   ta/candles/engulfing.py and (pending) ta/candles/engulfing_total.py.
"""


def range_covers(
    outer_low: float,
    outer_high: float,
    inner_low: float,
    inner_high: float,
    strict: bool = False,
) -> bool:
    """
    True if [outer_low, outer_high] contains [inner_low, inner_high].

    strict=False (default): inclusive at both edges -- an inner range whose
    edge exactly matches the outer range's edge still counts as covered.
    This matches ta/candles/engulfing.py's (and engulfing_total.py's)
    original, unchanged-by-default behavior.

    strict=True: requires the outer range to strictly exceed the inner
    range's edges rather than just meet them. [CANDLES-002] from the
    earlier engulfing.py audit resolved this way -- made configurable per
    call rather than picked silently for everyone.

    Callers are responsible for passing each pair as (low, high); this
    function does not validate or reorder malformed ranges.
    """
    if strict:
        return outer_low < inner_low and outer_high > inner_high
    return outer_low <= inner_low and outer_high >= inner_high
