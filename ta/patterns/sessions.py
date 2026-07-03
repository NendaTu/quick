"""
Trading Sessions and Market Open Strategy (Filter)

Features:
- Tracks Core and Overnight sessions for major global hubs (US, UK/EU, Japan, Hong Kong).
- All times are handled in 'America/Toronto' (EST/EDT) for consistency.
- Handles extended weekend overnight sessions (Friday close to Monday open).
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, time, timedelta
from ta.utils import convert_to_local
import config

# --- Hub Configurations (All times in EST) ---
# Format: (core_start_min, core_end_min)
def to_min(h, m): return h * 60 + m

HUBS = {
    'US': {
        'core': (to_min(9, 30), to_min(16, 0)),
        'overnight': (to_min(16, 0), to_min(9, 30))
    },
    'UK_EU': {
        'core': (to_min(3, 0), to_min(11, 30)),
        'overnight': (to_min(11, 30), to_min(3, 0))
    },
    'JAPAN': {
        'core': (to_min(19, 0), to_min(1, 0)),
        'overnight': (to_min(1, 0), to_min(19, 0))
    },
    'HK': {
        'core': (to_min(20, 30), to_min(4, 0)),
        'overnight': (to_min(4, 0), to_min(20, 30))
    }
}

def is_time_in_range(target_min: int, start_min: int, end_min: int) -> bool:
    if start_min <= end_min:
        return start_min <= target_min < end_min
    else: # Crosses midnight
        return target_min >= start_min or target_min < end_min

def get_current_hub_context(timestamp_s: float) -> Dict:
    """
    Identifies which hub's core or overnight session is active.
    """
    dt = convert_to_local(timestamp_s)
    current_min = dt.hour * 60 + dt.minute

    active_hubs = []
    for hub_name, sessions in HUBS.items():
        if is_time_in_range(current_min, *sessions['core']):
            active_hubs.append({'hub': hub_name, 'type': 'core'})
        if is_time_in_range(current_min, *sessions['overnight']):
            active_hubs.append({'hub': hub_name, 'type': 'overnight'})

    return {
        'dt': dt,
        'weekday': dt.weekday(),
        'active_hubs': active_hubs
    }

def identify_overnight_range(ohlcv: List[dict], now_ts: float) -> Dict:
    """
    Identifies the high/low range of the most recent overnight session for the current hub.
    Uses the provided now_ts to determine the hub context.
    """
    if not ohlcv: return {}

    ctx = get_current_hub_context(now_ts)
    now_min = ctx['dt'].hour * 60 + ctx['dt'].minute

    # 1. Determine which hub's killzone we are in
    target_hub = None
    for hub_name, sessions in HUBS.items():
        # Killzone: First 2 hours of core session
        if is_time_in_range(now_min, sessions['core'][0], sessions['core'][0] + 120):
            target_hub = hub_name
            break

    if not target_hub:
        return {}

    # 2. Find range from previous Core End to current Core Start
    # We scan the provided ohlcv (assumed to be 1H for efficiency)
    ov_high = -1.0
    ov_low = 1e12
    found = False

    # Target period: candles where hub was in 'overnight' status AND before now_ts
    for c in reversed(ohlcv):
        if c['ts'] >= now_ts: continue

        c_dt = convert_to_local(c['ts'])
        c_min = c_dt.hour * 60 + c_dt.minute

        # Is this hub's status 'overnight' at this candle?
        hub_ov = is_time_in_range(c_min, HUBS[target_hub]['overnight'][0], HUBS[target_hub]['overnight'][1])

        # Weekend extension: Saturday and Sunday are always part of the 'overnight' range
        # for a Monday morning open.
        if c_dt.weekday() >= 5: hub_ov = True

        if hub_ov:
            ov_high = max(ov_high, c['h'])
            ov_low = min(ov_low, c['l'])
            found = True
        elif found:
            # We reached the previous Core session, stop scanning
            break

    if not found: return {}

    return {
        'overnight_high': ov_high,
        'overnight_low': ov_low,
        'hub': target_hub
    }

def identify_sessions(ohlcv: List[dict]) -> Dict:
    """Legacy support."""
    if not ohlcv: return {}
    ctx = get_current_hub_context(ohlcv[-1]['ts'])
    res = {'current_session': None}
    for hub in ctx['active_hubs']:
        if hub['type'] == 'core':
            res['current_session'] = hub['hub']
            break
    return res

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
    if not ohlcv: return None
    ctx = get_current_hub_context(ohlcv[-1]['ts'])
    if not ctx['active_hubs']: return None
    return {
        "side": "both",
        "entry_price": ohlcv[-1]['c'],
        "stop_price": 0,
        "exit_price": 0,
        "metadata": ctx
    }
