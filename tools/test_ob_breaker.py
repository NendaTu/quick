import pytest
from ta.patterns.ob import detect_order_blocks, compute_atr_series
from ta.patterns.breaker import detect_breakers

def test_compute_atr_series():
    # Simple verification of contemporary volatility series calculation
    highs = [1.1] * 20
    lows = [0.9] * 20
    closes = [1.0] * 20
    atr_series = compute_atr_series(highs, lows, closes, period=5)
    assert len(atr_series) == 20
    assert atr_series[5] > 0.0
    assert atr_series[19] > 0.0

def test_detect_order_blocks():
    # Verify that a clear impulsive block is discovered and mitigated correctly
    ohlcv = []
    # Base candles with zero volatility, keeping subsequent candles outside of OB range [9.5, 10.1]
    for i in range(25):
        if i >= 12:
            ohlcv.append({"ts": 1000 + i, "o": 11.0, "h": 11.1, "l": 10.9, "c": 11.0, "v": 100})
        else:
            ohlcv.append({"ts": 1000 + i, "o": 10.0, "h": 10.1, "l": 9.9, "c": 10.0, "v": 100})

    # Set index 9 to not be a doji so it doesn't trigger secondary OB signals
    ohlcv[9] = {"ts": 1009, "o": 10.1, "h": 10.2, "l": 9.9, "c": 10.0, "v": 100}

    # Setup an OB at index 10: Bearish candle (10) followed by dynamic Bullish impulse (11)
    ohlcv[10] = {"ts": 1010, "o": 10.0, "h": 10.1, "l": 9.5, "c": 9.6, "v": 100} # Bearish OB anchor [9.5, 10.1]
    ohlcv[11] = {"ts": 1011, "o": 9.6, "h": 11.5, "l": 9.5, "c": 11.4, "v": 100} # Impulse breakout

    # Check unmitigated state
    res = detect_order_blocks(ohlcv, period=5)
    assert res['ob_active_count'] == 1
    assert res['latest_ob_type'] == 'bullish'
    assert len(res['active_obs']) == 1

    # Now mitigate it by dipping next candle low into its range [9.5, 10.1]
    ohlcv[24] = {"ts": 1024, "o": 11.0, "h": 11.1, "l": 9.8, "c": 10.9, "v": 100} # Mitigating dip
    res_mitigated = detect_order_blocks(ohlcv, period=5)
    assert res_mitigated['ob_active_count'] == 0
    assert res_mitigated['latest_ob_type'] is None

def test_detect_breakers():
    # Verify that failed order blocks turn into breakers
    ohlcv = []
    for i in range(25):
        if i >= 12:
            ohlcv.append({"ts": 1000 + i, "o": 11.0, "h": 11.1, "l": 10.9, "c": 11.0, "v": 100})
        else:
            ohlcv.append({"ts": 1000 + i, "o": 10.0, "h": 10.1, "l": 9.9, "c": 10.0, "v": 100})

    # Set index 9 to not be a doji so it doesn't trigger secondary OB signals
    ohlcv[9] = {"ts": 1009, "o": 10.1, "h": 10.2, "l": 9.9, "c": 10.0, "v": 100}

    # Setup an OB at index 10: Bearish candle (10) followed by Bullish impulse (11)
    ohlcv[10] = {"ts": 1010, "o": 10.0, "h": 10.1, "l": 9.5, "c": 9.6, "v": 100} # Bearish OB anchor [9.5, 10.1]
    ohlcv[11] = {"ts": 1011, "o": 9.6, "h": 11.5, "l": 9.5, "c": 11.4, "v": 100} # Impulse breakout

    # Now break it by closing well below its bottom (9.5) at index 15
    ohlcv[15] = {"ts": 1015, "o": 9.4, "h": 9.5, "l": 9.1, "c": 9.2, "v": 100} # Breaks bottom (invalidation)

    res = detect_breakers(ohlcv, period=5)
    assert res['breaker_count'] == 1
    assert res['latest_breaker_type'] == 'bearish'
    assert len(res['breakers']) == 1

def test_no_look_ahead_bias():
    # Setup ohlcv
    ohlcv = []
    for i in range(25):
        ohlcv.append({"ts": 1000 + i, "o": 10.0, "h": 10.1, "l": 9.9, "c": 10.0, "v": 100})

    # Run A: Baseline
    highs = [c['h'] for c in ohlcv[:-1]]
    lows = [c['l'] for c in ohlcv[:-1]]
    closes = [c['c'] for c in ohlcv[:-1]]
    atr_series_A = compute_atr_series(highs, lows, closes, period=5)

    # Run B: Perturb a candle well in the future (candle 20)
    ohlcv_perturbed = [dict(c) for c in ohlcv]
    ohlcv_perturbed[20] = {"ts": 1020, "o": 15.0, "h": 16.5, "l": 14.5, "c": 15.0, "v": 100}

    highs_perturbed = [c['h'] for c in ohlcv_perturbed[:-1]]
    lows_perturbed = [c['l'] for c in ohlcv_perturbed[:-1]]
    closes_perturbed = [c['c'] for c in ohlcv_perturbed[:-1]]
    atr_series_B = compute_atr_series(highs_perturbed, lows_perturbed, closes_perturbed, period=5)

    # Index 5 is before candle 20, so its ATR must remain identical
    assert abs(atr_series_A[5] - atr_series_B[5]) < 1e-9
    # Index 10 is before candle 20, so its ATR must remain identical
    assert abs(atr_series_A[10] - atr_series_B[10]) < 1e-9

def test_validation_and_failures():
    # 1. Invalid keys
    with pytest.raises(ValueError, match="missing required OHLCV keys"):
        detect_order_blocks([{"ts": 1000, "o": 10.0, "h": 10.1}], period=5)

    # 2. Chronological failure
    with pytest.raises(ValueError, match="not in chronological order"):
        detect_order_blocks([
            {"ts": 1000, "o": 10.0, "h": 10.1, "l": 9.9, "c": 10.0},
            {"ts": 999, "o": 10.0, "h": 10.1, "l": 9.9, "c": 10.0}
        ], period=5)

    # 3. Invalid Period
    with pytest.raises(ValueError, match="greater than 0"):
        detect_order_blocks([{"ts": 1000, "o": 10.0, "h": 10.1, "l": 9.9, "c": 10.0}], period=0)
