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
    assert res['nearest_ob_type'] == 'bullish'
    assert len(res['active_obs']) == 1

    # Now mitigate it by dipping next candle low into its range [9.5, 10.1]
    ohlcv[24] = {"ts": 1024, "o": 11.0, "h": 11.1, "l": 9.8, "c": 10.9, "v": 100} # Mitigating dip
    res_mitigated = detect_order_blocks(ohlcv, period=5)
    assert res_mitigated['ob_active_count'] == 0
    assert res_mitigated['nearest_ob_type'] is None

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
    assert res['nearest_breaker_type'] == 'bearish'
    assert len(res['breakers']) == 1
