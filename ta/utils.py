"""
1. Summary: General math, rolling window, and localized timezone converters.
2. Description: Provides SMA, EMA, and timezone helper tools. Translates exchange UTC timestamps to America/Toronto for accurate session mapping.
3. Context: Imported by almost all indicators and session detection modules.
"""
import math
from datetime import datetime, timezone
from typing import List, Dict
import functools

# --- Configuration ---
TIMEZONE = "America/Toronto"

try:
    import pytz
    _local_tz = pytz.timezone(TIMEZONE)
    _utc_tz = pytz.UTC
except ImportError:
    try:
        import zoneinfo
        _local_tz = zoneinfo.ZoneInfo(TIMEZONE)
    except ImportError:
        # Fallback if zoneinfo is not supported/missing DB (like old Python / stripped environments)
        # America/Toronto is UTC-5 (or UTC-4 in daylight savings). Fall back to simple UTC-5 offset.
        from datetime import timedelta, timezone as dt_timezone
        _local_tz = dt_timezone(timedelta(hours=-5))
    _utc_tz = timezone.utc

@functools.lru_cache(maxsize=10000)
def convert_to_local(timestamp_s: float) -> datetime:
    """
    Converts a Unix timestamp to a localized datetime object.
    [PERF] Cached to avoid expensive pytz/datetime operations on repetitive timestamps.
    """
    utc_dt = datetime.fromtimestamp(timestamp_s, tz=_utc_tz)
    return utc_dt.astimezone(_local_tz)

def is_within_time_window(timestamp_s: float, start_hm: str, end_hm: str) -> bool:
    """
    Checks if a timestamp falls within a specific HH:MM window in the local timezone.

    PERFORMANCE: This version avoids strptime by using simple integer comparisons.
    """
    dt = convert_to_local(timestamp_s)
    current_min = dt.hour * 60 + dt.minute

    # Parse HH:MM into minutes once
    h1, m1 = map(int, start_hm.split(':'))
    h2, m2 = map(int, end_hm.split(':'))
    start_min = h1 * 60 + m1
    end_min = h2 * 60 + m2

    if start_min <= end_min:
        return start_min <= current_min <= end_min
    else: # Crosses midnight
        return current_min >= start_min or current_min <= end_min

def calculate_sma(data: List[float], period: int) -> float:
    """Simple Moving Average."""
    if len(data) < period:
        return sum(data) / len(data) if data else 0.0
    return sum(data[-period:]) / period
