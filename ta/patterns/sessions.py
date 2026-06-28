"""
Trading Sessions and Market Open Tracking

Calculates and tracks Session Highs, Session Lows, and Market Open prices
for Asia, London, and New York.

Identification (EST):
- Asian: 18:00 - 02:00
- London: 02:00 - 08:00
- NY: 08:00 - 16:00
"""

from typing import List, Dict, Optional
from ta.utils import convert_to_local

# --- Internal Configuration ---
ENABLED = True
SESSIONS = {
    'asia': (18, 2),
    'london': (2, 8),
    'ny': (8, 16)
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
