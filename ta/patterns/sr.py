"""
1. Summary: Horizontal Support and Resistance locator.
2. Description: Detects horizontal floors and ceilings based on historical candle touch frequencies.
3. Context: Provides baseline zones for breakout and bounce strategies.
"""
from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Internal Configuration ---
ENABLED = True
TOLERANCE_PCT = 0.002 # 0.2% price tolerance for "touches"

# Default Strategy Settings
DEFAULT_TARGET_ROE = 0.01
SL_TICK_BUFFER = 0.0001

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for Support/Resistance strategy.
    """
    if len(ohlcv) < 50:
        return None

    # Parse Parameters
    mode = params[0].lower() if params and len(params) > 0 else 'bounce'
    rrr_override = float(params[1]) if params and len(params) > 1 else None

    # 1. Identify Levels
    sr_info = identify_sr(ohlcv)
    res = sr_info['sr_resistance']
    sup = sr_info['sr_support']

    curr = ohlcv[-1]
    entry_side = None
    target_level = None

    # 2. Strategy Logic
    if mode == 'bounce':
        # Overlaps support but stays above
        if curr['l'] <= sup and curr['c'] > sup:
            entry_side = "buy"
            target_level = sup
        # Overlaps resistance but stays below
        elif curr['h'] >= res and curr['c'] < res:
            entry_side = "sell"
            target_level = res
    else: # breakout
        # Closes above resistance
        if curr['c'] > res:
            entry_side = "buy"
            target_level = res
        # Closes below support
        elif curr['c'] < sup:
            entry_side = "sell"
            target_level = sup

    if not entry_side: return None

    # 3. Entry/Exit Calculations
    entry = curr['c']
    if entry_side == 'buy':
        stop = target_level * (1 - SL_TICK_BUFFER)
    else:
        stop = target_level * (1 + SL_TICK_BUFFER)

    if stop == entry: return None

    entry_maker = (config.ENTRY_ORDER_TYPE == "limit")
    tp_maker = (config.TP_ORDER_TYPE == "limit")

    if rrr_override is not None:
        target_roe = calculate_target_roe_for_rrr(rrr_override, entry, stop, 20, entry_maker=entry_maker)
    else:
        target_roe = DEFAULT_TARGET_ROE

    tp = calculate_tp_for_roe(entry, target_roe, entry_side, 20, entry_maker=entry_maker, exit_maker=tp_maker)

    return {
        "side": entry_side,
        "entry_price": entry,
        "stop_price": stop,
        "exit_price": tp,
        "metadata": {"mode": mode, "level": target_level}
    }

def identify_sr(ohlcv: List[dict]) -> Dict:
    """
    Finds key horizontal support and resistance levels.
    """
    if not ENABLED or len(ohlcv) < 50:
        return {}

    swings = detect_swings(ohlcv, strength=3)
    highs = swings['highs']
    lows = swings['lows']

    current_price = ohlcv[-1]['c']

    def find_levels(points):
        levels = []
        for p in points:
            # Check for clusters (Simplified: just find unique price points)
            is_new = True
            for lv in levels:
                if abs(p['price'] / lv['price'] - 1) < TOLERANCE_PCT:
                    lv['touches'] += 1
                    is_new = False
                    break
            if is_new:
                levels.append({'price': p['price'], 'touches': 1})
        return sorted(levels, key=lambda x: x['touches'], reverse=True)

    resistance_levels = find_levels(highs)
    support_levels = find_levels(lows)

    # Filter for nearest active levels
    nearest_res = next((l for l in resistance_levels if l['price'] > current_price), None)
    nearest_sup = next((l for l in support_levels if l['price'] < current_price), None)

    return {
        'sr_resistance': nearest_res['price'] if nearest_res else None,
        'sr_support': nearest_sup['price'] if nearest_sup else None,
        'res_touches': nearest_res['touches'] if nearest_res else 0,
        'sup_touches': nearest_sup['touches'] if nearest_sup else 0
    }
