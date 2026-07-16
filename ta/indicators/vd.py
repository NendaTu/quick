"""
Volume Delta (VD) Indicator Module

How it works:
1. Volume Delta measures the difference between buying and selling volume executed
   via market orders at the ask and bid prices.
2. Formula: Delta = Market Buys (Aggressive Buyers) – Market Sells (Aggressive Sellers)
3. Aggressive buyers execute buy orders at the ask, driving the price upward.
4. Aggressive sellers execute sell orders at the bid, driving the price downward.
5. This file provides stateless, clean, and robust calculations for Volume Delta.
"""

from typing import List, Dict, Any, Union
import math

def compute_volume_delta(data: List[Dict[str, Any]], is_trades: bool = True) -> Dict[str, Any]:
    """
    Computes the Volume Delta.

    :param data: If is_trades is True, a list of market trades. Each trade must be a dictionary
                 containing 'size' (float) and 'side' ('buy' or 'sell').
                 If is_trades is False, a list of candlesticks. Each candlestick must be a dictionary
                 optionally containing 'buy_vol' (float) and 'sell_vol' (float).
    :param is_trades: Boolean indicating whether 'data' represents trades list or candle list.
    :return: Dict containing:
             - "delta": Absolute Volume Delta (Market Buys - Market Sells)
             - "total_vol": Combined Buy and Sell volume
             - "normalized_delta": Normalized Delta (Delta / Total Volume) between -1.0 and 1.0
    """
    if not data:
        return {
            "delta": 0.0,
            "total_vol": 0.0,
            "normalized_delta": 0.0
        }

    buy_vol = 0.0
    sell_vol = 0.0

    if is_trades:
        # 1. Processing Market Trades (ticks)
        for idx, t in enumerate(data):
            if not all(k in t for k in ('size', 'side')):
                raise ValueError(f"Trade at index {idx} is missing required keys ('size', 'side'): {t}")

            size = t['size']
            side = t['side']

            # Type and numeric bounds validation [REPAIR]
            if not isinstance(size, (int, float)):
                raise ValueError(f"Trade size at index {idx} must be numeric, got {size} ({type(size)})")
            if math.isnan(size) or math.isinf(size) or size < 0.0:
                raise ValueError(f"Trade size at index {idx} has invalid, NaN, or negative value: {size}")
            if side not in ('buy', 'sell'):
                raise ValueError(f"Trade side at index {idx} must be 'buy' or 'sell', got '{side}'")

            if side == 'buy':
                buy_vol += float(size)
            else:
                sell_vol += float(size)
    else:
        # 2. Processing Candlesticks
        for idx, c in enumerate(data):
            buy = c.get('buy_vol', 0.0)
            sell = c.get('sell_vol', 0.0)

            # Type and numeric bounds validation [REPAIR]
            for key, val in (('buy_vol', buy), ('sell_vol', sell)):
                if not isinstance(val, (int, float)):
                    raise ValueError(f"Candle {key} at index {idx} must be numeric, got {val} ({type(val)})")
                if math.isnan(val) or math.isinf(val) or val < 0.0:
                    raise ValueError(f"Candle {key} at index {idx} has invalid, NaN, or negative value: {val}")

            buy_vol += float(buy)
            sell_vol += float(sell)

    delta = buy_vol - sell_vol
    total_vol = buy_vol + sell_vol
    normalized_delta = delta / total_vol if total_vol > 0.0 else 0.0

    return {
        "delta": delta,
        "total_vol": total_vol,
        "normalized_delta": normalized_delta
    }
