"""
1. Summary: Technical support and resistance horizontal price level locator.
2. Description: Locates local swing peak and trough extremes with tie-breakers, clusters them based on range budget spreads, and checks chronological candle closes to identify level breakout states.
3. Context: Utilized by support/resistance trading strategies and point-of-interest filters.
"""
import logging
from typing import List, Dict, Any, Optional

log = logging.getLogger("scalper.ta.levels")

def _find_swing_points(ohlcv: List[dict], body_or_wick: str, period: int) -> List[dict]:
    """
    Identifies local swing points (peaks and troughs) with window size period.
    Two candles tied at the same extreme resolve to the earlier candle (tie-breaking).
    """
    swing_points = []
    for i in range(period, len(ohlcv) - period):
        curr = ohlcv[i]
        is_peak = True
        is_trough = True

        if body_or_wick == "body":
            p_up = max(curr['o'], curr['c'])
            p_down = min(curr['o'], curr['c'])

            # Verify peak (earlier candle tie-breaker)
            for j in range(i - period, i):
                val = max(ohlcv[j]['o'], ohlcv[j]['c'])
                if p_up <= val:
                    is_peak = False
                    break
            if is_peak:
                for j in range(i + 1, i + period + 1):
                    val = max(ohlcv[j]['o'], ohlcv[j]['c'])
                    if p_up < val:
                        is_peak = False
                        break

            # Verify trough (earlier candle tie-breaker)
            for j in range(i - period, i):
                val_down = min(ohlcv[j]['o'], ohlcv[j]['c'])
                if p_down >= val_down:
                    is_trough = False
                    break
            if is_trough:
                for j in range(i + 1, i + period + 1):
                    val_down = min(ohlcv[j]['o'], ohlcv[j]['c'])
                    if p_down > val_down:
                        is_trough = False
                        break
        else: # "wick"
            p_up = curr['h']
            p_down = curr['l']

            # Verify peak (earlier candle tie-breaker)
            for j in range(i - period, i):
                if p_up <= ohlcv[j]['h']:
                    is_peak = False
                    break
            if is_peak:
                for j in range(i + 1, i + period + 1):
                    if p_up < ohlcv[j]['h']:
                        is_peak = False
                        break

            # Verify trough (earlier candle tie-breaker)
            for j in range(i - period, i):
                if p_down >= ohlcv[j]['l']:
                    is_trough = False
                    break
            if is_trough:
                for j in range(i + 1, i + period + 1):
                    if p_down > ohlcv[j]['l']:
                        is_trough = False
                        break

        if is_peak:
            swing_points.append({"price": p_up, "ts": curr['ts'], "type": "peak"})
        if is_trough:
            swing_points.append({"price": p_down, "ts": curr['ts'], "type": "trough"})

    return swing_points

def _cluster_points(swing_points: List[dict], range_width_pct: float) -> List[dict]:
    """
    Groups closely situated swing points into clusters while ensuring no cluster's
    total price spread exceeds the range_width_pct budget of its minimum price.
    """
    sorted_points = sorted(swing_points, key=lambda x: x["price"])
    clusters = []

    for p in sorted_points:
        placed = False
        p_price = p["price"]

        for cluster in clusters:
            # Check budget constraint with candidate point
            prices = [x["price"] for x in cluster["points"]] + [p_price]
            min_p = min(prices)
            max_p = max(prices)
            budget = min_p * range_width_pct

            if (max_p - min_p) <= (budget + 1e-9):
                cluster["points"].append(p)
                cluster["price"] = sum(x["price"] for x in cluster["points"]) / len(cluster["points"])
                placed = True
                break

        if not placed:
            clusters.append({
                "price": p_price,
                "points": [p]
            })

    return clusters

def _is_level_broken(ohlcv: List[dict], timestamps: List[float], level_price: float, last_touch_ts: float, last_touch_type: str) -> bool:
    """
    Evaluates if subsequent price action has crossed / broken this level.
    """
    for c in ohlcv:
        if c['ts'] > last_touch_ts:
            # Check if a candle close crosses the level based on peak/trough origin
            if last_touch_type == "peak" and c['c'] > level_price:
                return True
            if last_touch_type == "trough" and c['c'] < level_price:
                return True
    return False

def identify_levels(
    ohlcv: List[dict],
    body_or_wick: str = "wick",
    period: int = 5,
    min_touches: int = 2,
    range_width_pct: float = 0.002
) -> Dict[str, List[dict]]:
    """
    Identifies support and resistance levels from historical candles,
    categorizing them into support/resistance and active/historical.
    """
    # 0. Input validation
    if body_or_wick not in ("body", "wick"):
        raise ValueError(f"body_or_wick must be 'body' or 'wick', got {body_or_wick}")
    if period <= 0:
        raise ValueError(f"period must be greater than 0, got {period}")
    if min_touches <= 0:
        raise ValueError(f"min_touches must be greater than 0, got {min_touches}")
    if range_width_pct <= 0:
        raise ValueError(f"range_width_pct must be greater than 0, got {range_width_pct}")

    # Check for chronological sorting
    for idx, c in enumerate(ohlcv):
        if idx > 0 and c['ts'] <= ohlcv[idx-1]['ts']:
            raise ValueError(f"Candles are not chronologically sorted: index {idx} ts {c['ts']} <= index {idx-1} ts {ohlcv[idx-1]['ts']}")

    if len(ohlcv) < (period * 2 + 1):
        return {
            "active_support": [], "active_resistance": [],
            "historical_support": [], "historical_resistance": []
        }

    # 1. Identify local swing points
    swing_points = _find_swing_points(ohlcv, body_or_wick, period)

    # 2. Cluster swing points into levels
    clusters = _cluster_points(swing_points, range_width_pct)

    # Filter out clusters with fewer than min_touches
    valid_clusters = [c for c in clusters if len(c["points"]) >= min_touches]

    # 3. Categorize into Support vs Resistance and Active vs Historical
    current_price = ohlcv[-1]['c']

    active_support = []
    active_resistance = []
    historical_support = []
    historical_resistance = []

    for cluster in valid_clusters:
        level_price = cluster["price"]
        points = cluster["points"]

        # Last touch timestamp defines when the level was formed/last active
        last_touch_ts = max(x["ts"] for x in points)
        last_touch_type = [x["type"] for x in points if x["ts"] == last_touch_ts][0]

        # Extract timestamps of points
        timestamps = [x["ts"] for x in points]

        # Check if subsequent price action has crossed / broken this level
        is_broken = _is_level_broken(ohlcv, timestamps, level_price, last_touch_ts, last_touch_type)

        level_details = {
            "price": level_price,
            "touches": len(points),
            "last_touch_ts": last_touch_ts,
            "points": points
        }

        # Determine if Support (below current) or Resistance (above current)
        if level_price < current_price:
            if is_broken:
                historical_support.append(level_details)
            else:
                active_support.append(level_details)
        else:
            if is_broken:
                historical_resistance.append(level_details)
            else:
                active_resistance.append(level_details)

    # Sort levels by price for easy lookup
    active_support = sorted(active_support, key=lambda x: x["price"], reverse=True) # Highest support closest to current_price
    active_resistance = sorted(active_resistance, key=lambda x: x["price"]) # Lowest resistance closest to current_price
    historical_support = sorted(historical_support, key=lambda x: x["price"], reverse=True)
    historical_resistance = sorted(historical_resistance, key=lambda x: x["price"])

    return {
        "active_support": active_support,
        "active_resistance": active_resistance,
        "historical_support": historical_support,
        "historical_resistance": historical_resistance
    }
