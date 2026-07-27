"""
1. Summary: Session Sweep Reversal signal calculator.
2. Description: Computes entry triggers once a session sweep completes and a low-timeframe market structure shift confirms.
3. Context: Provides signal logic for advanced session-based strategies.
"""
from typing import List, Dict, Optional
from ta.patterns.sessions import is_in_killzone
from ta.patterns.sweep import detect_sweeps
from ta.patterns.liquidity import identify_liquidity
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
ENABLED = True
SL_TICK_BUFFER = 0.0001
MIN_SL_PCT = 0.001  # 0.1% Minimum SL distance to prevent fee traps

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for Session Sweep Reversal strategy.
    """
    if len(ohlcv) < 51:
        return None

    # Parse Parameters
    rrr_override = float(params[0]) if params and len(params) > 0 else None

    # 1. Identify active sweep reversal state
    sweep_info = detect_sweep_reversal(ohlcv)
    if not sweep_info.get('active'):
        return None

    bias = sweep_info['target_side']  # 'bullish' or 'bearish'
    entry_side = 'buy' if bias == 'bullish' else 'sell'

    curr = ohlcv[-1]
    entry = curr['c']

    # 2. Get SL and TP (Session/Liquidity Targets)
    if entry_side == 'buy':
        stop = curr['l'] * (1 - SL_TICK_BUFFER)
        # Enforce minimum SL width guard to prevent fee-trap trades
        min_sl = entry * (1 - MIN_SL_PCT)
        if stop > min_sl:
            stop = min_sl
    else:
        stop = curr['h'] * (1 + SL_TICK_BUFFER)
        # Enforce minimum SL width guard to prevent fee-trap trades
        min_sl = entry * (1 + MIN_SL_PCT)
        if stop < min_sl:
            stop = min_sl

    # TP: Target the opposite liquidity pool
    liq = identify_liquidity(ohlcv[:-1], lookback=50)
    if entry_side == 'buy':
        target_price = liq['bsl_level']
    else:
        target_price = liq['ssl_level']

    # 3. Calculate Final TP (Parity check)
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
            "killzone": sweep_info['killzone'],
            "target_roe": target_roe,
            "bypass_external_filters": True  # Align with sweeps defaults
        }
    }

def detect_sweep_reversal(ohlcv: List[dict]) -> Dict:
    """
    Checks if a valid session sweep reversal occurred within or immediately preceding a killzone.
    """
    if not ENABLED or not ohlcv:
        return {}

    last_ts = ohlcv[-1]['ts']
    active_kz = is_in_killzone(last_ts, buffer_minutes=30)

    if not active_kz:
        return {'active': False, 'killzone': None}

    # Search the last 20 candles for a clean sweep
    found_sweep = None
    for i in range(len(ohlcv)-1, max(0, len(ohlcv)-21), -1):
        sd = detect_sweeps(ohlcv[:i+1])
        if sd.get('sweep_detected'):
            found_sweep = sd
            break

    is_valid = False
    target_side = None
    if found_sweep:
        sweep_ts = found_sweep.get('sweep_timestamp')
        target_side = 'bullish' if found_sweep.get('sweep_type') == 'sell_side' else 'bearish'

        # Verify that the sweep itself also happened within or preceding a killzone
        sweep_kz = is_in_killzone(sweep_ts, buffer_minutes=30)
        if sweep_kz is not None:
            is_valid = True

    return {
        'active': is_valid,
        'killzone': active_kz,
        'target_side': target_side
    }
