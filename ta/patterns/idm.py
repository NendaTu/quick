"""
Institutional Delivery Model (IDM) Recognition

Predicts price delivery from one liquidity pool to another during specific
high-volatility EST time windows (London/NY killzones).

Time Windows (EST):
- London Killzone: 02:00 - 05:00
- NY Killzone: 08:00 - 11:00
- NY PM Killzone: 14:00 - 16:00

Logic:
Within windows, after a sweep, target opposite extreme.
"""

from typing import List, Dict, Optional
from ta.utils import is_within_time_window
from ta.patterns.sweep import detect_sweeps

# --- Internal Configuration ---
ENABLED = True
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

    # Within a killzone, check if a sweep just occurred
    sweep_data = detect_sweeps(ohlcv)

    return {
        'idm_active': sweep_data.get('sweep_detected', False),
        'killzone': active_kz,
        'idm_target_side': 'bullish' if sweep_data.get('sweep_type') == 'sell_side' else 'bearish' if sweep_data.get('sweep_type') == 'buy_side' else None
    }
