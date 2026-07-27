"""
1. Summary: Cumulative Volume Delta (CVD) rolling series calculator.
2. Description: Tracks aggressive buying and selling volume deltas accumulated over a rolling time window.
3. Context: Used by feature extraction and scoring modules to measure institutional order flow direction.
"""
from typing import List, Dict, Any
import math

def compute_cvd_series(ohlcv: List[Dict[str, Any]]) -> List[float]:
    """
    Computes the Cumulative Volume Delta (CVD) series.

    :param ohlcv: List of candlesticks, where each candlestick must be a dictionary
                  optionally containing 'buy_vol' (float) and 'sell_vol' (float).
    :return: A list of floats representing the cumulative sum of Volume Deltas over time,
             matching the length of the input ohlcv list.
    """
    if not ohlcv:
        return []

    cvd_series = []
    current_cvd = 0.0

    for idx, c in enumerate(ohlcv):
        buy = c.get('buy_vol', 0.0)
        sell = c.get('sell_vol', 0.0)

        # Type and numeric bounds validation [REPAIR]
        for key, val in (('buy_vol', buy), ('sell_vol', sell)):
            if not isinstance(val, (int, float)):
                raise ValueError(f"Candle {key} at index {idx} must be numeric, got {val} ({type(val)})")
            if math.isnan(val) or math.isinf(val) or val < 0.0:
                raise ValueError(f"Candle {key} at index {idx} has invalid, NaN, or negative value: {val}")

        delta = float(buy) - float(sell)
        current_cvd += delta
        cvd_series.append(current_cvd)

    return cvd_series
