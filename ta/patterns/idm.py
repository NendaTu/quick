"""
Institutional Delivery Model (IDM) Recognition

Predicts price delivery from one liquidity pool to another during specific
high-volatility time windows.
"""

from typing import List, Dict, Optional
from ta.utils import is_within_time_window, convert_to_local
from ta.patterns.sweep import detect_sweeps

# --- Configuration ---
# Toggle to enable/disable IDM detection.
ENABLED = True

# High-probability time windows (EST) for institutional delivery.
KILLZONES = {
    'london': ('02:00', '05:00'),
    'ny_am': ('08:00', '11:00'),
    'ny_pm': ('14:00', '16:00'),
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

    sweep_data = detect_sweeps(ohlcv)

    is_valid_idm = False
    if sweep_data.get('sweep_detected'):
        sweep_ts = sweep_data.get('sweep_timestamp')
        if sweep_ts:
            sweep_dt = convert_to_local(sweep_ts)
            now_dt = convert_to_local(last_ts)
            if sweep_dt.date() == now_dt.date():
                if is_within_time_window(sweep_ts, KILLZONES[active_kz][0], KILLZONES[active_kz][1]):
                    is_valid_idm = True

    return {
        'idm_active': is_valid_idm,
        'killzone': active_kz,
        'idm_target_side': 'bullish' if sweep_data.get('sweep_type') == 'sell_side' else 'bearish' if sweep_data.get('sweep_type') == 'buy_side' else None
    }
