"""
1. Summary: Regression tests for horizontal support/resistance level clustering.
2. Description: Runs assertions against swing points, clustering spread budgets, and breakout logic.
3. Context: Verifies the stability of ta/levels.py.
"""
from ta.levels import identify_levels, _find_swing_points, _cluster_points, _is_level_broken


def C(ts, o, h, l, c):
    return {"ts": ts, "o": o, "h": h, "l": l, "c": c}


# ---------------------------------------------------------------------------
# Swing-point detection
# ---------------------------------------------------------------------------

def test_swing_point_tie_breaking_dedupes_flat_top():
    """Two candles tied at the same high must yield ONE peak, not two."""
    candles = [
        C(0, 99.6, 99.9, 99.5, 99.7),
        C(1, 99.8, 100.0, 99.6, 99.9),
        C(2, 100.3, 100.50, 100.2, 100.4),   # candle A: tied high
        C(3, 100.35, 100.50, 100.25, 100.45),  # candle B: same high as A
        C(4, 99.8, 100.0, 99.6, 99.9),
        C(5, 99.6, 99.9, 99.5, 99.7),
    ]
    sp = _find_swing_points(candles, "wick", 1)
    peaks = [p for p in sp if p["type"] == "peak" and abs(p["price"] - 100.50) < 1e-9]
    assert len(peaks) == 1, f"expected 1 deduplicated peak, got {len(peaks)}"
    assert peaks[0]["ts"] == 2, "tie should resolve to the earlier candle"


def test_swing_point_distinct_prices_are_not_merged():
    """Sanity check that dedup logic doesn't over-merge genuinely distinct extremes."""
    candles = [
        C(0, 99.0, 99.2, 98.9, 99.0),
        C(1, 99.5, 99.7, 99.4, 99.5),
        C(2, 100.0, 101.0, 99.9, 100.0),   # distinct peak, h=101.0
        C(3, 99.5, 99.7, 99.4, 99.5),
        C(4, 99.0, 99.2, 98.9, 99.0),
        C(5, 99.5, 99.7, 99.4, 99.5),
        C(6, 100.0, 103.0, 99.9, 100.0),   # distinct peak, h=103.0 (not tied with above)
        C(7, 99.5, 99.7, 99.4, 99.5),
        C(8, 99.0, 99.2, 98.9, 99.0),
    ]
    sp = _find_swing_points(candles, "wick", 1)
    peaks = sorted(p["price"] for p in sp if p["type"] == "peak")
    assert peaks == [101.0, 103.0], f"expected two distinct peaks, got {peaks}"


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def test_clustering_stays_within_range_width_pct():
    """No cluster's price spread should exceed its range_width_pct budget."""
    range_pct = 0.002
    prices = [round(100.00 + 0.05 * i, 2) for i in range(16)]
    swing_points = [{"price": p, "ts": i, "type": "trough"} for i, p in enumerate(prices)]

    clusters = _cluster_points(swing_points, range_pct)

    assert len(clusters) > 1, "16 points spanning 0.75 at a 0.2%% tolerance must not collapse into one cluster"
    for cluster in clusters:
        pts = [x["price"] for x in cluster["points"]]
        spread = max(pts) - min(pts)
        budget = min(pts) * range_pct
        assert spread <= budget + 1e-9, (
            f"cluster spread {spread:.4f} exceeds range_width_pct budget {budget:.4f}"
        )


def test_clustering_groups_points_within_tolerance():
    """Points genuinely within tolerance of each other should still cluster together."""
    swing_points = [
        {"price": 100.00, "ts": 1, "type": "trough"},
        {"price": 100.05, "ts": 2, "type": "trough"},
        {"price": 100.10, "ts": 3, "type": "trough"},
    ]
    clusters = _cluster_points(swing_points, range_width_pct=0.002)
    assert len(clusters) == 1
    assert len(clusters[0]["points"]) == 3


# ---------------------------------------------------------------------------
# Break detection
# ---------------------------------------------------------------------------

def test_break_detection_uses_actual_last_touch_type():
    """
    The touch that is chronologically last (by ts) determines break
    direction -- not whichever point happened to have the lower price.
    """
    timestamps = [201]
    ohlcv = [C(201, 100.20, 100.60, 100.10, 100.50)]  # closes well above the level
    level_price = 100.025
    last_touch_ts = 200

    # The chronologically-last touch was a peak -> a close above should break it.
    assert _is_level_broken(ohlcv, timestamps, level_price, last_touch_ts, "peak") is True

    # (Sanity: the reverse direction on the same candle would NOT be broken.)
    assert _is_level_broken(ohlcv, timestamps, level_price, last_touch_ts, "trough") is False


def test_break_detection_requires_close_beyond_level_not_just_wick():
    """A wick through the level that closes back on the original side is a
    retest, not a break."""
    timestamps = [101]
    level_price = 100.00
    # Wicks below and above the level intrabar, but closes above it (support held).
    ohlcv = [C(101, 100.30, 100.60, 99.90, 100.30)]

    assert _is_level_broken(ohlcv, timestamps, level_price, 100, "trough") is False


def test_break_detection_gap_through_is_still_caught():
    """A candle that gaps cleanly past the level (no wick straddle at all)
    must still be caught via the close-based check."""
    timestamps = [101]
    level_price = 100.00
    # Whole candle sits above the level -- no wick straddle, but a real break.
    ohlcv = [C(101, 100.50, 100.80, 100.40, 100.70)]

    assert _is_level_broken(ohlcv, timestamps, level_price, 100, "peak") is True


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _assert_raises_value_error(**kwargs):
    try:
        identify_levels(**kwargs)
    except ValueError:
        return
    raise AssertionError(f"expected ValueError for kwargs={kwargs}")


def test_rejects_unsorted_timestamps():
    candles = [C(5, 1, 1, 1, 1)] + [C(i, 1, 1, 1, 1) for i in range(20)]
    _assert_raises_value_error(ohlcv=candles, period=1)


def test_rejects_invalid_body_or_wick():
    candles = [C(i, 1, 1, 1, 1) for i in range(20)]
    _assert_raises_value_error(ohlcv=candles, body_or_wick="wik")


def test_rejects_non_positive_period():
    candles = [C(i, 1, 1, 1, 1) for i in range(20)]
    _assert_raises_value_error(ohlcv=candles, period=0)


def test_rejects_non_positive_min_touches():
    candles = [C(i, 1, 1, 1, 1) for i in range(20)]
    _assert_raises_value_error(ohlcv=candles, min_touches=0)


def test_rejects_non_positive_range_width_pct():
    candles = [C(i, 1, 1, 1, 1) for i in range(20)]
    _assert_raises_value_error(ohlcv=candles, range_width_pct=0)


def test_empty_result_when_insufficient_candles():
    candles = [C(i, 1, 1, 1, 1) for i in range(5)]
    result = identify_levels(candles, period=5)
    assert result == {
        "active_support": [], "active_resistance": [],
        "historical_support": [], "historical_resistance": []
    }


# ---------------------------------------------------------------------------
# End-to-end structural invariants
# ---------------------------------------------------------------------------

def _make_random_walk(n, seed=42):
    import random
    rng = random.Random(seed)
    price = 100.0
    candles = []
    for ts in range(n):
        o = price
        c = max(1.0, o + rng.uniform(-0.15, 0.15))
        h = max(o, c) + rng.uniform(0, 0.05)
        l = min(o, c) - rng.uniform(0, 0.05)
        candles.append(C(ts, round(o, 4), round(h, 4), round(l, 4), round(c, 4)))
        price = c
    return candles


def test_support_is_below_and_resistance_is_above_current_price():
    candles = _make_random_walk(500)
    result = identify_levels(candles)
    current_price = candles[-1]['c']
    for lv in result["active_support"] + result["historical_support"]:
        assert lv["price"] < current_price
    for lv in result["active_resistance"] + result["historical_resistance"]:
        assert lv["price"] >= current_price


def test_output_is_deterministic():
    candles = _make_random_walk(500)
    r1 = identify_levels(candles)
    r2 = identify_levels(candles)
    assert r1 == r2


def test_every_valid_cluster_meets_min_touches():
    candles = _make_random_walk(500)
    min_touches = 3
    result = identify_levels(candles, min_touches=min_touches)
    for bucket in result.values():
        for lv in bucket:
            assert lv["touches"] >= min_touches


# ---------------------------------------------------------------------------
# Standalone runner (no pytest required)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import traceback

    tests = [(name, fn) for name, fn in list(globals().items())
             if name.startswith("test_") and callable(fn)]

    passed, failed = 0, 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
            passed += 1
        except Exception:
            print(f"FAIL  {name}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
