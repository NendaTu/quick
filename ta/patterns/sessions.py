"""
Trading Sessions and Market Open Strategy (Filter)

How it works:
1. This is a "Filter" strategy. It doesn't trade on its own but restricts
   other strategies to only trigger during specific institutional hours.
2. It tracks the major global trading sessions:
   - Asian: 18:00 - 02:00 (EST)
   - London: 02:00 - 08:00 (EST)
   - New York (NY): 08:00 - 16:00 (EST)
3. Killzones: High-volatility "Open" periods (Default: first 2 hours of a session).
4. Signal Logic:
   - Returns "both" (allowing any direction) if the current time is within
     the requested session or killzone.
5. Backtesting command: `python backtest.py sessions [name] [is_killzone]`
   - [name]: 'asia', 'london', or 'ny'.
   - [is_killzone]: 'true' to only match the session open (first 2 hours).
"""

from typing import List, Dict, Optional
from ta.utils import convert_to_local
import config

# --- Internal Configuration ---
ENABLED = True
SESSIONS = {
    'asia': (18, 2),
    'london': (2, 8),
    'ny': (8, 16)
}

# Default Strategy Settings
KILLZONE_DURATION = 2 # Hours

def get_signal(ohlcv: List[dict], timeframe: str, params: List[str] = None) -> Optional[Dict]:
    """
    Backtesting entry point for Sessions filter.
    """
    if not ohlcv or not params:
        return None

    target_session = params[0].lower()
    only_killzone = (params[1].lower() == 'true') if len(params) > 1 else False

    # Get local time for current candle
    curr = ohlcv[-1]
    dt = convert_to_local(curr['ts'])
    hour = dt.hour

    # 1. Determine current session
    active_sess = None
    sess_start_hour = 0

    if hour >= 18 or hour < 2:
        active_sess = 'asia'
        sess_start_hour = 18
    elif 2 <= hour < 8:
        active_sess = 'london'
        sess_start_hour = 2
    elif 8 <= hour < 16:
        active_sess = 'ny'
        sess_start_hour = 8

    # 2. Check match
    if active_sess != target_session:
        return None

    if only_killzone:
        # Calculate hours since session start
        if hour < sess_start_hour: # Crossed midnight (Asia)
            hours_in = (hour + 24) - sess_start_hour
        else:
            hours_in = hour - sess_start_hour

        if hours_in >= KILLZONE_DURATION:
            return None

    # Returns "both" to allow any simultaneous strategy to trigger
    return {
        "side": "both",
        "entry_price": curr['c'],
        "stop_price": 0, # Not used for filter
        "exit_price": 0, # Not used for filter
        "metadata": {"session": active_sess, "is_killzone": only_killzone}
    }

def identify_sessions(ohlcv: List[dict]) -> Dict:
    """
    Calculates high, low, and open for the current and previous session.
    """
    if not ENABLED or not ohlcv:
        return {}

    # This implementation normally needs a large lookback or DB persistence
    # to be 100% accurate across restarts.
    # Here we process the available OHLCV.

    session_data = {
        'asia_h': 0, 'asia_l': 0, 'asia_o': 0,
        'london_h': 0, 'london_l': 0, 'london_o': 0,
        'ny_h': 0, 'ny_l': 0, 'ny_o': 0,
        'current_session': None
    }

    for c in ohlcv:
        dt = convert_to_local(c['ts'])
        hour = dt.hour

        active_sess = None
        if hour >= 18 or hour < 2: active_sess = 'asia'
        elif 2 <= hour < 8: active_sess = 'london'
        elif 8 <= hour < 16: active_sess = 'ny'

        if active_sess:
            h_key = f"{active_sess}_h"
            l_key = f"{active_sess}_l"
            o_key = f"{active_sess}_o"

            if session_data[o_key] == 0:
                session_data[o_key] = c['o']

            session_data[h_key] = max(session_data[h_key], c['h'])
            if session_data[l_key] == 0: session_data[l_key] = c['l']
            session_data[l_key] = min(session_data[l_key], c['l'])

            session_data['current_session'] = active_sess

    return session_data
