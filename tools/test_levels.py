import pytest
from ta.levels import identify_levels

def test_identify_levels_empty_or_small():
    # Test that short history returns empty lists
    ohlcv = [{"ts": 1000, "o": 1.0, "h": 1.1, "l": 0.9, "c": 1.0, "v": 10}]
    res = identify_levels(ohlcv, period=5)
    assert res["active_support"] == []
    assert res["active_resistance"] == []

def test_identify_levels_logic():
    # Construct a clean 25-candle history where a support level is formed at 1.0
    # and a resistance level is formed at 2.0
    ohlcv = []

    # Baseline price level around 1.5
    for i in range(25):
        # Default neutral candle
        c = {"ts": 1000 + i * 60, "o": 1.5, "h": 1.6, "l": 1.4, "c": 1.5, "v": 100}

        # Form a Support touch at candle 5 (price dips to 1.0)
        if i == 5:
            c = {"ts": 1000 + i * 60, "o": 1.5, "h": 1.6, "l": 1.0, "c": 1.5, "v": 100}
        # Form a Resistance touch at candle 10 (price peaks to 2.0)
        elif i == 10:
            c = {"ts": 1000 + i * 60, "o": 1.5, "h": 2.0, "l": 1.4, "c": 1.5, "v": 100}
        # Form a Second Support touch at candle 15 (price dips to 1.01)
        elif i == 15:
            c = {"ts": 1000 + i * 60, "o": 1.5, "h": 1.6, "l": 1.01, "c": 1.5, "v": 100}
        # Form a Second Resistance touch at candle 20 (price peaks to 1.99)
        elif i == 20:
            c = {"ts": 1000 + i * 60, "o": 1.5, "h": 1.99, "l": 1.4, "c": 1.5, "v": 100}

        ohlcv.append(c)

    # Latest close is 1.5
    # Active support is around 1.005 (touches: 2)
    # Active resistance is around 1.995 (touches: 2)
    res = identify_levels(ohlcv, body_or_wick="wick", period=2, min_touches=2, range_width_pct=0.02)

    # Verify supports (finding the support closest to 1.0)
    supports = [x for x in res["active_support"] if abs(x["price"] - 1.0) < 0.05]
    assert len(supports) == 1
    assert pytest.approx(supports[0]["price"], abs=0.01) == 1.005
    assert supports[0]["touches"] == 2

    # Verify resistances (finding the resistance closest to 2.0)
    resistances = [x for x in res["active_resistance"] if abs(x["price"] - 2.0) < 0.05]
    assert len(resistances) == 1
    assert pytest.approx(resistances[0]["price"], abs=0.01) == 1.995
    assert resistances[0]["touches"] == 2

def test_identify_levels_broken_state():
    # Construct history where a level is formed at 2.0, and subsequently broken
    ohlcv = []
    for i in range(25):
        c = {"ts": 1000 + i * 60, "o": 1.5, "h": 1.6, "l": 1.4, "c": 1.5, "v": 100}

        # Peak 1 at candle 5
        if i == 5:
            c = {"ts": 1000 + i * 60, "o": 1.5, "h": 2.0, "l": 1.4, "c": 1.5, "v": 100}
        # Peak 2 at candle 12
        elif i == 12:
            c = {"ts": 1000 + i * 60, "o": 1.5, "h": 2.01, "l": 1.4, "c": 1.5, "v": 100}
        # Price breaks completely above 2.0 to 2.5 at candle 18
        elif i == 18:
            c = {"ts": 1000 + i * 60, "o": 2.5, "h": 2.6, "l": 2.4, "c": 2.5, "v": 100}

        ohlcv.append(c)

    # Current price is 2.5
    # The level at 2.0 is now below the current close (Support category!)
    # And since candle 18 broke above it (timestamp 1180 > last touch 1120), it is marked as Historical
    res = identify_levels(ohlcv, body_or_wick="wick", period=2, min_touches=2, range_width_pct=0.01)

    # Verify that the 2.0 level has transitioned to historical resistance (broken level above 1.5)
    print("DEBUG RES:", res)
    hist_resistances = [x for x in res["historical_resistance"] if abs(x["price"] - 2.0) < 0.05]
    assert len(hist_resistances) == 1
    assert pytest.approx(hist_resistances[0]["price"], abs=0.01) == 2.005
