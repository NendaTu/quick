"""
TA Utility Module

Provides shared math functions and timezone conversion utilities for technical analysis.
All time-based patterns convert exchange UTC timestamps to 'America/Toronto' for
session and killzone alignment.
"""

import math
from datetime import datetime
import pytz
from typing import List

# --- Configuration ---
TIMEZONE = "America/Toronto"

def convert_to_local(timestamp_s: float) -> datetime:
    """Converts a Unix timestamp to a localized datetime object."""
    utc_dt = datetime.fromtimestamp(timestamp_s, tz=pytz.UTC)
    local_tz = pytz.timezone(TIMEZONE)
    return utc_dt.astimezone(local_tz)

def is_within_time_window(timestamp_s: float, start_hm: str, end_hm: str) -> bool:
    """
    Checks if a timestamp falls within a specific HH:MM window in the local timezone.
    Args:
        timestamp_s: Unix timestamp in seconds.
        start_hm: Start time string 'HH:MM'.
        end_hm: End time string 'HH:MM'.
    """
    dt = convert_to_local(timestamp_s)
    current_time = dt.time()

    start_time = datetime.strptime(start_hm, "%H:%M").time()
    end_time = datetime.strptime(end_hm, "%H:%M").time()

    if start_time <= end_time:
        return start_time <= current_time <= end_time
    else: # Crosses midnight
        return current_time >= start_time or current_time <= end_time

def calculate_sma(data: List[float], period: int) -> float:
    """Simple Moving Average."""
    if len(data) < period:
        return sum(data) / len(data) if data else 0.0
    return sum(data[-period:]) / period
