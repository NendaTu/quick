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

# --- ICT Killzones (America/Toronto EST/EDT) ---
KILLZONES = {
    'london': ('02:00', '05:00'),
    'ny_am': ('08:00', '11:00'),
    'ny_pm': ('14:00', '16:00'),
}

def is_in_killzone(timestamp_s: float, buffer_minutes: int = 30) -> Optional[str]:
    """
    Checks if a timestamp falls within any ICT Killzone, or immediately preceding it.
    Returns the name of the killzone ('london', 'ny_am', 'ny_pm') if active, or None.

    If buffer_minutes > 0, it also matches the window buffer_minutes prior to the killzone's start.
    """
    dt = convert_to_local(timestamp_s)
    current_min = dt.hour * 60 + dt.minute

    for kz, (start_hm, end_hm) in KILLZONES.items():
        h1, m1 = map(int, start_hm.split(':'))
        h2, m2 = map(int, end_hm.split(':'))
        start_min = h1 * 60 + m1
        end_min = h2 * 60 + m2

        # Adjust start time to include buffer
        buffered_start_min = (start_min - buffer_minutes) % 1440

        if buffered_start_min <= end_min:
            in_range = buffered_start_min <= current_min <= end_min
        else: # Crosses midnight
            in_range = current_min >= buffered_start_min or current_min <= end_min

        if in_range:
            return kz

    return None

_ov_range_cache = {}
_core_range_cache = {}

def is_time_in_range(target_min: int, start_min: int, end_min: int) -> bool:
    if start_min <= end_min:
        return start_min <= target_min < end_min
    else: # Crosses midnight
        return target_min >= start_min or target_min < end_min

def is_core_session(timestamp_s: float, hub: str) -> bool:
    if hub not in HUBS: return False
    dt = convert_to_local(timestamp_s)
    if dt.weekday() >= 5: return False # Weekend
    current_min = dt.hour * 60 + dt.minute
    return is_time_in_range(current_min, *HUBS[hub]['core'])

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
    Targeted for Day Trading (trading the Core session).
    """
    if not ohlcv: return {}

    # Cache key based on the current hour and hub context
    ctx = get_current_hub_context(now_ts)
    now_hour_ts = (now_ts // 3600) * 3600

    # Determine target hub for current Core Session monitoring
    now_min = ctx['dt'].hour * 60 + ctx['dt'].minute
    target_hub = None
    for hub_name, sessions in HUBS.items():
        if is_time_in_range(now_min, sessions['core'][0], sessions['core'][1]):
            target_hub = hub_name
            break

    if not target_hub:
        return {}

    cache_key = f"{now_hour_ts}_{target_hub}"
    if cache_key in _ov_range_cache:
        return _ov_range_cache[cache_key]

    # 2. Find range from previous Core End to current Core Start
    ov_high = -1.0
    ov_low = 1e12
    found = False
    first_c = None
    last_c = None

    # Target period: candles where hub was in 'overnight' status AND before now_ts
    for c in reversed(ohlcv[-120:]):
        if c['ts'] >= now_ts: continue

        c_dt = convert_to_local(c['ts'])
        c_min = c_dt.hour * 60 + c_dt.minute

        hub_ov = is_time_in_range(c_min, HUBS[target_hub]['overnight'][0], HUBS[target_hub]['overnight'][1])
        if c_dt.weekday() >= 5: hub_ov = True

        if hub_ov:
            ov_high = max(ov_high, c['h'])
            ov_low = min(ov_low, c['l'])
            if not last_c:
                last_c = c
            first_c = c
            found = True
        elif found:
            break

    if not found: return {}

    res = {
        'overnight_high': ov_high,
        'overnight_low': ov_low,
        'hub': target_hub,
        'open': first_c['o'] if first_c else None,
        'close': last_c['c'] if last_c else None
    }

    if len(_ov_range_cache) > 500: _ov_range_cache.clear()
    _ov_range_cache[cache_key] = res

    return res

def identify_core_range(ohlcv: List[dict], now_ts: float) -> Dict:
    """
    Identifies the high/low range of the most recent Core session for the current hub.
    Targeted for Overnight Trading (trading the Overnight session).
    """
    if not ohlcv: return {}

    ctx = get_current_hub_context(now_ts)
    now_hour_ts = (now_ts // 3600) * 3600

    # Determine target hub for current overnight trading
    target_hub = None
    for hub in ctx['active_hubs']:
        if hub['type'] == 'overnight':
            target_hub = hub['hub']
            break

    if not target_hub:
        return {}

    cache_key = f"{now_hour_ts}_{target_hub}"
    if cache_key in _core_range_cache:
        return _core_range_cache[cache_key]

    # Find the most recent continuous block of 'core' session candles for this hub
    core_high = -1.0
    core_low = 1e12
    found = False
    first_c = None
    last_c = None

    for c in reversed(ohlcv[-120:]):
        if c['ts'] >= now_ts: continue

        c_dt = convert_to_local(c['ts'])
        c_min = c_dt.hour * 60 + c_dt.minute

        hub_core = is_time_in_range(c_min, HUBS[target_hub]['core'][0], HUBS[target_hub]['core'][1])
        # Weekend candles are never 'core'
        if c_dt.weekday() >= 5: hub_core = False

        if hub_core:
            core_high = max(core_high, c['h'])
            core_low = min(core_low, c['l'])
            if not last_c:
                last_c = c
            first_c = c
            found = True
        elif found:
            # We found the start of the core session block, stop scanning
            break

    if not found: return {}

    res = {
        'core_high': core_high,
        'core_low': core_low,
        'hub': target_hub,
        'open': first_c['o'] if first_c else None,
        'close': last_c['c'] if last_c else None
    }

    if len(_core_range_cache) > 500: _core_range_cache.clear()
    _core_range_cache[cache_key] = res

    return res

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
