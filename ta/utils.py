"""
TA Utility Module

Provides shared math functions and timezone conversion utilities for technical analysis.
All time-based patterns convert exchange UTC timestamps to 'America/Toronto' for
session and killzone alignment.
"""

import math
from datetime import datetime
import pytz
from typing import List, Dict
import functools

# --- Configuration ---
TIMEZONE = "America/Toronto"
_local_tz = pytz.timezone(TIMEZONE)

@functools.lru_cache(maxsize=10000)
def convert_to_local(timestamp_s: float) -> datetime:
    """
    Converts a Unix timestamp to a localized datetime object.
    [PERF] Cached to avoid expensive pytz/datetime operations on repetitive timestamps.
    """
    utc_dt = datetime.fromtimestamp(timestamp_s, tz=pytz.UTC)
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
