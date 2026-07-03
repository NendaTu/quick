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

def get_signal(ohlcv, tf, params=None, **kwargs) -> Optional[Dict]:
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

def identify_overnight_range(ohlcv: List[dict], prior_close_hour: int = 16) -> Dict:
    """
    Identifies the high/low range between the prior day's close (Default 16:00 EST)
    and the current session's open.
    """
    if not ohlcv:
        return {}

    # 1. Determine current session of the latest candle
    now_dt = convert_to_local(ohlcv[-1]['ts'])
    now_hour = now_dt.hour

    current_session = None
    session_open_hour = 0
    if now_hour >= 18 or now_hour < 2:
        current_session = 'asia'
        session_open_hour = 18
    elif 2 <= now_hour < 8:
        current_session = 'london'
        session_open_hour = 2
    elif 8 <= now_hour < 16:
        current_session = 'ny'
        session_open_hour = 8

    if not current_session:
        return {}

    # 2. Define the start of the overnight range (16:00 EST of the previous "trading day")
    # For NY, it's 16:00 yesterday to 09:30 today.
    # For London, it's 16:00 yesterday to 02:00 today.
    # For Asia, it's 16:00 today (since Asia starts at 18:00) to 18:00 today?
    # Wait, the prompt says: "prior day's close and current session's open".
    # Bitget/Crypto 24/7 close is typically 16:00 EST or 00:00 UTC.
    # The user specifically cited NY: 16:00 yesterday to 09:30 today.

    # Logic: Look back from the latest candle to find the start of the current session,
    # then look further back to find the 16:00 mark.

    overnight_high = -1.0
    overnight_low = 1e12

    # To find the overnight range, we need enough data.
    # We'll scan backwards from the latest candle.

    in_overnight = False
    for i in range(len(ohlcv)-1, -1, -1):
        c = ohlcv[i]
        dt = convert_to_local(c['ts'])

        # Is this candle before current session open?
        # A simple check: if we are in NY (starts at 8), we want candles before 8.
        # But we also want to stop at 16:00 of the "previous" day.

        # If we reached prior_close_hour, we stop.
        if dt.hour == prior_close_hour and dt.minute == 0:
            break

        # If we are between prior_close_hour and session_open_hour
        is_ov = False
        if session_open_hour == 18: # Asia
            if dt.hour >= prior_close_hour and dt.hour < 18: is_ov = True
        elif session_open_hour == 2: # London
            # 16:00 yesterday to 02:00 today
            if dt.hour >= prior_close_hour or dt.hour < 2: is_ov = True
        elif session_open_hour == 8: # NY
            # 16:00 yesterday to 08:00 today
            if dt.hour >= prior_close_hour or dt.hour < 8: is_ov = True

        if is_ov:
            overnight_high = max(overnight_high, c['h'])
            overnight_low = min(overnight_low, c['l'])
            in_overnight = True

    if not in_overnight:
        return {}

    return {
        'overnight_high': overnight_high,
        'overnight_low': overnight_low,
        'session': current_session
    }
