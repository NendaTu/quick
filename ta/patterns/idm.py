"""
SMC Inducement (IDM) Detection Module

Under Smart Money Concepts (SMC):
1. Market Structure mapping is tracked via Swing Highs and Swing Lows.
2. A Break of Structure (BOS) confirms the active trend direction:
   - Bullish BOS: Price closes above the most recent Swing High.
   - Bearish BOS: Price closes below the most recent Swing Low.
3. Once a BOS occurs, the market establishes an Inducement (IDM) level:
   - Bullish Trend: The IDM level is the lowest low of the most recent valid minor pullback
     before the new high was created. To be valid (not an inside bar), the candle
     forming that pullback low must have its high successfully taken out by a subsequent candle.
   - Bearish Trend: The IDM level is the highest high of the most recent valid minor pullback
     before the new low was created. To be valid, the candle forming that pullback high
     must have its low successfully taken out by a subsequent candle.
4. An Inducement Sweep occurs when:
   - Bullish: Current candle wicks below the Bullish IDM level but closes back above it.
   - Bearish: Current candle wicks above the Bearish IDM level but closes back below it.
"""

from typing import List, Dict, Optional
from ta.patterns.swings import detect_swings
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
ENABLED = True
DEFAULT_SWING_STRENGTH = 2
DEFAULT_LOOKBACK = 100
SL_TICK_BUFFER = 0.0001
DEFAULT_TARGET_ROE = 0.01

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for the SMC Inducement (IDM) strategy.
    """
    if len(ohlcv) < 50:
        return None

    # Parse Parameters
    swing_strength = int(params[0]) if params and len(params) > 0 else DEFAULT_SWING_STRENGTH
    lookback = int(params[1]) if params and len(params) > 1 else DEFAULT_LOOKBACK
    rrr_override = float(params[2]) if params and len(params) > 2 else None

    # Identify true SMC Inducement sweep state
    idm_info = detect_idm(ohlcv, swing_strength=swing_strength, lookback=lookback)
    if not idm_info.get('idm_active'):
        return None

    idm_type = idm_info['idm_type'] # 'bullish_sweep' or 'bearish_sweep'
    entry_side = 'buy' if idm_type == 'bullish_sweep' else 'sell'

    curr = ohlcv[-1]
    entry = curr['c']
    idm_level = idm_info['idm_level']

    # Get asset tick size
    price_place = 2
    tick_size = 0.01

    # SL: 1 tick past the current candle's sweep extreme (which swept the IDM level)
    if entry_side == 'buy':
        stop = curr['l'] - tick_size
        # Fallback to standard 0.5% stop if FVG or stop distance is invalid
        if stop >= entry:
            stop = entry * 0.995
    else:
        stop = curr['h'] + tick_size
        if stop <= entry:
            stop = entry * 1.005

    # Enforce minimum stop-loss distance guard (at least 0.1% of entry price to avoid zero-width fee traps)
    min_stop_dist = entry * 0.001
    if abs(entry - stop) < min_stop_dist:
        if entry_side == 'buy':
            stop = entry - min_stop_dist
        else:
            stop = entry + min_stop_dist

    # Take Profit: Target the opposite swing extreme
    swings = detect_swings(ohlcv[-lookback:], strength=swing_strength)
    if entry_side == 'buy':
        target_price = swings['highs'][-1]['price'] if swings['highs'] else (entry * 1.01)
    else:
        target_price = swings['lows'][-1]['price'] if swings['lows'] else (entry * 0.99)

    # Use target_price to derive target_roe
    entry_maker = (config.ENTRY_ORDER_TYPE == "limit")
    tp_maker = (config.TP_ORDER_TYPE == "limit")

    from tools.trading_utils import calculate_roe
    target_roe = calculate_roe(entry, target_price, entry_side, 20, entry_maker=entry_maker, exit_maker=tp_maker)

    # RRR override takes precedence if set
    if rrr_override is not None:
        target_roe = calculate_target_roe_for_rrr(rrr_override, entry, stop, 20, entry_maker=entry_maker)

    if target_roe <= 0:
        return None

    tp = calculate_tp_for_roe(entry, target_roe, entry_side, 20, entry_maker=entry_maker, exit_maker=tp_maker)

    return {
        "side": entry_side,
        "entry_price": entry,
        "stop_price": stop,
        "exit_price": tp,
        "metadata": {
            "idm_level": idm_level,
            "idm_type": idm_type,
            "target_roe": target_roe
        }
    }

def detect_idm(ohlcv: List[dict], swing_strength: int = DEFAULT_SWING_STRENGTH, lookback: int = DEFAULT_LOOKBACK) -> Dict:
    """
    SMC Inducement (IDM) Level & Sweep Detector.
    Returns:
        {
            'idm_active': bool,      # True if an Inducement Sweep occurred in the current candle
            'idm_level': float,      # Sourced IDM price level
            'idm_type': str,         # 'bullish_sweep' or 'bearish_sweep'
            'structure': str         # 'bullish' or 'bearish' trend structure
        }
    """
    if not ENABLED or len(ohlcv) < 15:
        return {'idm_active': False, 'idm_level': None, 'idm_type': None, 'structure': 'neutral'}

    # Use closed history to map market structure (prevent current candle repainting)
    closed_ohlcv = ohlcv[:-1]

    swings = detect_swings(closed_ohlcv, strength=swing_strength)
    highs = swings['highs']
    lows = swings['lows']

    if not highs or not lows:
        return {'idm_active': False, 'idm_level': None, 'idm_type': None, 'structure': 'neutral'}

    # 1. Determine Trend and Break of Structure (BOS) using the shareable single-concern module
    from ta.patterns.structure import identify_structure
    struct = identify_structure(closed_ohlcv, strength=swing_strength)
    struct_sig = struct.get('structure_signal') or ''

    structure = 'neutral'
    if 'bullish' in struct_sig:
        structure = 'bullish'
    elif 'bearish' in struct_sig:
        structure = 'bearish'

    if structure == 'neutral':
        return {'idm_active': False, 'idm_level': None, 'idm_type': None, 'structure': 'neutral'}

    idm_level = None
    idm_type = None

    # 2. Locate the most recent valid minor pullback (Inducement level)
    if structure == 'bullish':
        # Bullish IDM: Find the lowest point of the most recent minor pullback before the highest high
        # We loop backward from the highest high candle in our lookback range
        highest_c_idx = max(range(len(closed_ohlcv)), key=lambda idx: closed_ohlcv[idx]['h'])

        # Look for the minor pullback low before this highest high
        pullback_low_found = None
        for i in range(highest_c_idx - 1, max(1, highest_c_idx - 40), -1):
            curr_c = closed_ohlcv[i]
            prev_c = closed_ohlcv[i-1]

            # Is this candle a local minor pullback low?
            if curr_c['l'] < prev_c['l']:
                # Validate the pullback: subsequent candle must break its high (not an inside bar)
                has_high_broken = False
                for j in range(i + 1, min(len(closed_ohlcv), i + 10)):
                    if closed_ohlcv[j]['h'] > curr_c['h']:
                        has_high_broken = True
                        break

                if has_high_broken:
                    pullback_low_found = curr_c['l']
                    break

        if pullback_low_found is not None:
            idm_level = pullback_low_found
            idm_type = 'bullish_sweep'

    elif structure == 'bearish':
        # Bearish IDM: Find the highest point of the most recent minor pullback before the lowest low
        lowest_c_idx = max(range(len(closed_ohlcv)), key=lambda idx: -closed_ohlcv[idx]['l'])

        pullback_high_found = None
        for i in range(lowest_c_idx - 1, max(1, lowest_c_idx - 40), -1):
            curr_c = closed_ohlcv[i]
            prev_c = closed_ohlcv[i-1]

            # Is this candle a local minor pullback high?
            if curr_c['h'] > prev_c['h']:
                # Validate the pullback: subsequent candle must break its low
                has_low_broken = False
                for j in range(i + 1, min(len(closed_ohlcv), i + 10)):
                    if closed_ohlcv[j]['l'] < curr_c['l']:
                        has_low_broken = True
                        break

                if has_low_broken:
                    pullback_high_found = curr_c['h']
                    break

        if pullback_high_found is not None:
            idm_level = pullback_high_found
            idm_type = 'bearish_sweep'

    if idm_level is None:
        return {'idm_active': False, 'idm_level': None, 'idm_type': None, 'structure': structure}

    # 3. Detect Sweep in the current (active) candle
    # Bullish Sweep: Current Low < idm_level AND current Close > idm_level
    # Bearish Sweep: Current High > idm_level AND current Close < idm_level
    curr_c = ohlcv[-1]
    is_sweep = False

    if idm_type == 'bullish_sweep':
        if curr_c['l'] < idm_level and curr_c['c'] > idm_level:
            is_sweep = True
    elif idm_type == 'bearish_sweep':
        if curr_c['h'] > idm_level and curr_c['c'] < idm_level:
            is_sweep = True

    return {
        'idm_active': is_sweep,
        'idm_level': idm_level,
        'idm_type': idm_type if is_sweep else None,
        'structure': structure
    }
