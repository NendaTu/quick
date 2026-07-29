"""
1. Summary: Checks Volume Delta and Cumulative Volume Delta numerical boundaries.
2. Description: Verifies that CVD computations are robust against missing values and NaN extremes.
3. Context: Validates correct execution of aggression indicators.
"""
import pytest
import math
from ta.indicators.vd import compute_volume_delta
from ta.indicators.cvd import compute_cvd_series

def test_compute_volume_delta_trades():
    # 1. Standard valid trades list
    trades = [
        {"size": 1.5, "side": "buy"},
        {"size": 2.5, "side": "sell"},
        {"size": 1.0, "side": "buy"}
    ]
    res = compute_volume_delta(trades, is_trades=True)
    assert pytest.approx(res["delta"], abs=1e-5) == 0.0 # (1.5 + 1.0) - 2.5 = 0.0
    assert pytest.approx(res["total_vol"], abs=1e-5) == 5.0
    assert pytest.approx(res["normalized_delta"], abs=1e-5) == 0.0

    # 2. Empty list
    res_empty = compute_volume_delta([], is_trades=True)
    assert res_empty["delta"] == 0.0
    assert res_empty["total_vol"] == 0.0
    assert res_empty["normalized_delta"] == 0.0

def test_compute_volume_delta_candles():
    # 1. Standard valid candles list
    candles = [
        {"buy_vol": 10.0, "sell_vol": 4.0},
        {"buy_vol": 5.0, "sell_vol": 8.0}
    ]
    res = compute_volume_delta(candles, is_trades=False)
    assert pytest.approx(res["delta"], abs=1e-5) == 3.0 # (10 + 5) - (4 + 8) = 15 - 12 = 3.0
    assert pytest.approx(res["total_vol"], abs=1e-5) == 27.0
    assert pytest.approx(res["normalized_delta"], abs=1e-5) == 3.0 / 27.0

def test_compute_cvd_series():
    # 1. Standard valid candles list
    candles = [
        {"buy_vol": 10.0, "sell_vol": 4.0}, # Delta = +6
        {"buy_vol": 5.0, "sell_vol": 8.0},  # Delta = -3
        {"buy_vol": 2.0, "sell_vol": 2.0}   # Delta = 0
    ]
    cvd = compute_cvd_series(candles)
    assert len(cvd) == 3
    assert pytest.approx(cvd[0], abs=1e-5) == 6.0
    assert pytest.approx(cvd[1], abs=1e-5) == 3.0
    assert pytest.approx(cvd[2], abs=1e-5) == 3.0

    # 2. Empty list
    assert compute_cvd_series([]) == []

def test_volume_delta_validations():
    # 1. Missing side key
    with pytest.raises(ValueError, match="missing required keys"):
        compute_volume_delta([{"size": 1.5}], is_trades=True)

    # 2. Non-numeric size
    with pytest.raises(ValueError, match="must be numeric"):
        compute_volume_delta([{"size": "1.5", "side": "buy"}], is_trades=True)

    # 3. NaN size
    with pytest.raises(ValueError, match="invalid, NaN, or negative"):
        compute_volume_delta([{"size": float('nan'), "side": "buy"}], is_trades=True)

    # 4. Infinity size
    with pytest.raises(ValueError, match="invalid, NaN, or negative"):
        compute_volume_delta([{"size": float('inf'), "side": "buy"}], is_trades=True)

    # 5. Negative size
    with pytest.raises(ValueError, match="invalid, NaN, or negative"):
        compute_volume_delta([{"size": -1.0, "side": "buy"}], is_trades=True)

    # 6. Invalid side
    with pytest.raises(ValueError, match="must be 'buy' or 'sell'"):
        compute_volume_delta([{"size": 1.0, "side": "neutral"}], is_trades=True)

def test_cvd_validations():
    # 1. Non-numeric candle buy_vol
    with pytest.raises(ValueError, match="must be numeric"):
        compute_cvd_series([{"buy_vol": "10.0", "sell_vol": 4.0}])

    # 2. NaN sell_vol
    with pytest.raises(ValueError, match="invalid, NaN, or negative"):
        compute_cvd_series([{"buy_vol": 10.0, "sell_vol": float('nan')}])

    # 3. Infinity buy_vol
    with pytest.raises(ValueError, match="invalid, NaN, or negative"):
        compute_cvd_series([{"buy_vol": float('inf'), "sell_vol": 4.0}])

    # 4. Negative sell_vol
    with pytest.raises(ValueError, match="invalid, NaN, or negative"):
        compute_cvd_series([{"buy_vol": 10.0, "sell_vol": -2.0}])
