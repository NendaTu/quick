"""
Institutional Delivery Model (IDM) Strategy

How it works:
1. This is an advanced "ICT-style" strategy. It predicts that once price "sweeps"
   liquidity on one side, it will be "delivered" to the opposite side's liquidity pool.
2. Timing is Critical: This model only triggers during specific high-probability
   time windows (London Open and NY Open killzones).
3. Signal Logic:
   - Buy: Triggered when a "Sell Side Sweep" (price wicks below a low) occurs
     during a killzone. The target is the nearest major High.
   - Sell: Triggered when a "Buy Side Sweep" (price wicks above a high) occurs
     during a killzone. The target is the nearest major Low.
4. Stop Loss (SL): Placed 1 tick beyond the sweep wick to ensure the reversal holds.
5. Take Profit (TP): Automatically targets the **opposite liquidity pool**, which
   often provides a very high Reward-to-Risk ratio.
6. Backtesting command: `python backtest.py idm [rrr_override]`
"""

from typing import List, Dict, Optional
from ta.utils import is_within_time_window, convert_to_local
from ta.patterns.sweep import detect_sweeps
from ta.patterns.liquidity import identify_liquidity
from tools.trading_utils import calculate_tp_for_roe, calculate_target_roe_for_rrr
import config

# --- Configuration ---
# Toggle to enable/disable IDM detection.
ENABLED = True

# High-probability time windows (EST) for institutional delivery.
KILLZONES = {
    'london': ('02:00', '05:00'),
    'ny_am': ('08:00', '11:00'),
    'ny_pm': ('14:00', '16:00'),
}

# Default Strategy Settings
DEFAULT_TARGET_ROE = 0.01
SL_TICK_BUFFER = 0.0001

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    """
    Backtesting entry point for IDM strategy.
    """
    if len(ohlcv) < 51:
        return None

    # Parse Parameters
    rrr_override = float(params[0]) if params and len(params) > 0 else None

    # 1. Identify IDM state
    idm_info = detect_idm(ohlcv)
    if not idm_info.get('idm_active'):
        return None

    bias = idm_info['idm_target_side'] # 'bullish' or 'bearish'
    entry_side = 'buy' if bias == 'bullish' else 'sell'

    curr = ohlcv[-1]
    entry = curr['c']

    # 2. Get SL and TP (Institutional Targets)
    # SL is the sweep wick extreme
    if entry_side == 'buy':
        stop = curr['l'] * (1 - SL_TICK_BUFFER)
    else:
        stop = curr['h'] * (1 + SL_TICK_BUFFER)

    # TP: IDM targets the opposite liquidity pool
    liq = identify_liquidity(ohlcv[:-1], lookback=50)
    if entry_side == 'buy':
        target_price = liq['bsl_level']
    else:
        target_price = liq['ssl_level']

    # 3. Calculate Final TP (Parity check)
    entry_maker = (config.ENTRY_ORDER_TYPE == "limit")
    tp_maker = (config.TP_ORDER_TYPE == "limit")

    # Use target_price to derive target_roe
    from tools.trading_utils import calculate_roe
    target_roe = calculate_roe(entry, target_price, entry_side, 20, entry_maker=entry_maker, exit_maker=tp_maker)

    # RRR override takes precedence if set
    if rrr_override is not None:
        target_roe = calculate_target_roe_for_rrr(rrr_override, entry, stop, 20, entry_maker=entry_maker)

    if target_roe <= 0: return None

    tp = calculate_tp_for_roe(entry, target_roe, entry_side, 20, entry_maker=entry_maker, exit_maker=tp_maker)

    return {
        "side": entry_side,
        "entry_price": entry,
        "stop_price": stop,
        "exit_price": tp,
        "metadata": {"killzone": idm_info['killzone'], "target_roe": target_roe}
    }

def detect_idm(ohlcv: List[dict]) -> Dict:
    """
    Checks if institutional delivery is active within killzones.
    """
    if not ENABLED or not ohlcv:
        return {}

    last_ts = ohlcv[-1]['ts']
    active_kz = None

    for kz, (start, end) in KILLZONES.items():
        if is_within_time_window(last_ts, start, end):
            active_kz = kz
            break

    if not active_kz:
        return {'idm_active': False, 'killzone': None}

    # [T-005] Refined IDM logic: Search for recent sweeps with strict temporal link
    # IDM delivery occurs AFTER a sweep. We scan the last 20 candles.
    found_sweep = None
    for i in range(len(ohlcv)-1, max(0, len(ohlcv)-21), -1):
        sd = detect_sweeps(ohlcv[:i+1])
        if sd.get('sweep_detected'):
            found_sweep = sd
            break

    is_valid_idm = False
    target_side = None
    if found_sweep:
        sweep_ts = found_sweep.get('sweep_timestamp')
        target_side = 'bullish' if found_sweep.get('sweep_type') == 'sell_side' else 'bearish'

        # Check if sweep was within the killzone OR immediately preceding (30m)
        kz_start_hm = KILLZONES[active_kz][0]
        kz_end_hm = KILLZONES[active_kz][1]

        in_kz = is_within_time_window(sweep_ts, kz_start_hm, kz_end_hm)

        # Preceding check: 30 mins before kz_start
        from datetime import datetime, timedelta
        kz_start_dt = datetime.strptime(kz_start_hm, "%H:%M")
        pre_start_dt = (kz_start_dt - timedelta(minutes=30)).time()

        sweep_dt_local = convert_to_local(sweep_ts).time()
        is_preceding = pre_start_dt <= sweep_dt_local < kz_start_dt.time()

        if in_kz or is_preceding:
            is_valid_idm = True

    return {
        'idm_active': is_valid_idm,
        'killzone': active_kz,
        'idm_target_side': target_side
    }
