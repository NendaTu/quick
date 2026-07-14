import logging
from typing import List, Dict, Any, Optional

log = logging.getLogger("scalper.ta.levels")

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

    :param ohlcv: List of candles
    :param body_or_wick: "body" (open/close) or "wick" (high/low) anchors
    :param period: Window size on either side to qualify a swing point (local extreme)
    :param min_touches: Minimum swing points required to form a level cluster
    :param range_width_pct: Relative percentage tolerance band for grouping points into a level
    :return: Dict containing:
             - "active_support": List of active support levels
             - "active_resistance": List of active resistance levels
             - "historical_support": List of broken/historical support levels
             - "historical_resistance": List of broken/historical resistance levels
    """
    if len(ohlcv) < (period * 2 + 1):
        return {
            "active_support": [], "active_resistance": [],
            "historical_support": [], "historical_resistance": []
        }

    # 1. Identify local swing points
    swing_points = []

    for i in range(period, len(ohlcv) - period):
        curr = ohlcv[i]
        is_peak = True
        is_trough = True

        if body_or_wick == "body":
            p_up = max(curr['o'], curr['c'])
            p_down = min(curr['o'], curr['c'])

            # Verify peak
            for j in range(i - period, i + period + 1):
                if j == i: continue
                val = max(ohlcv[j]['o'], ohlcv[j]['c'])
                if p_up < val:
                    is_peak = False
                val_down = min(ohlcv[j]['o'], ohlcv[j]['c'])
                if p_down > val_down:
                    is_trough = False
        else: # "wick"
            p_up = curr['h']
            p_down = curr['l']

            # Verify peak
            for j in range(i - period, i + period + 1):
                if j == i: continue
                if p_up < ohlcv[j]['h']:
                    is_peak = False
                if p_down > ohlcv[j]['l']:
                    is_trough = False

        if is_peak:
            swing_points.append({"price": p_up, "ts": curr['ts'], "type": "peak"})
        if is_trough:
            swing_points.append({"price": p_down, "ts": curr['ts'], "type": "trough"})

    # 2. Cluster swing points into levels
    # Sort swing points by price to cluster closely grouped points
    sorted_points = sorted(swing_points, key=lambda x: x["price"])
    clusters = []

    for p in sorted_points:
        placed = False
        p_price = p["price"]

        for cluster in clusters:
            # Calculate distance to current cluster average price
            avg_price = cluster["price"]
            threshold = avg_price * range_width_pct

            if abs(p_price - avg_price) <= threshold:
                cluster["points"].append(p)
                # Recalculate cluster average price
                cluster["price"] = sum(x["price"] for x in cluster["points"]) / len(cluster["points"])
                placed = True
                break

        if not placed:
            clusters.append({
                "price": p_price,
                "points": [p]
            })

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

        # Check if subsequent price action has crossed / broken this level
        is_broken = False
        last_touch_type = points[0]["type"] if points else "peak"

        for c in ohlcv:
            if c['ts'] > last_touch_ts:
                # 1. Check if candle range completely cuts/straddles the level
                if c['l'] < level_price < c['h']:
                    is_broken = True
                    break
                # 2. Check if a candle close crosses the level based on peak/trough origin
                if last_touch_type == "peak" and c['c'] > level_price:
                    is_broken = True
                    break
                if last_touch_type == "trough" and c['c'] < level_price:
                    is_broken = True
                    break

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
