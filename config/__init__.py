"""
1. Summary: Global application configuration package entrypoint.
2. Description: Instantiates the validated Settings object, extracts all parameters into flat package-level variables to ensure 100% backward compatibility, and exposes the ConfigContext class.
3. Context: Standard configuration interface imported by all system layers.
"""
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

# --- Mode & Environment Helper ---
def get_env_stripped(key, default=None):
    """
    Retrieves and strips single/double quotes from environment variables.
    Using this helper ensures environment configuration variables are loaded cleanly.
    """
    val = os.getenv(key, default)
    if val:
        return val.strip(' "').strip("'")
    return val

# Import settings classes
from config.settings import Settings

# Instantiate global settings
_settings = Settings()

# Dynamically populate package-level namespace to ensure 100% backward compatibility
# with existing "from config import *" or "import config" statements across the codebase.
for group_name in ["env", "risk", "assets", "execution", "strategy", "scoring", "logging_ui", "simulator"]:
    group = getattr(_settings, group_name)
    for k, v in group.__dict__.items():
        if k.isupper():
            globals()[k] = v

# Fallbacks and mode-aware DB paths (P2-11)
DB_PATH = os.environ.get("DB_PATH", f"data/market_data_{MODE.lower()}.db")

# Timeframe structures
ACTIVE_TIMEFRAME = "1m"
AVAILABLE_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1H", "4H", "1D"]
TF_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400, "1D": 86400}
MAX_START_DATE = datetime(2022, 6, 1, tzinfo=timezone.utc)
MAX_END_DATE = datetime(2026, 6, 1, tzinfo=timezone.utc)

# --- Config Context Class for Dependency Injection [ARCH-003] ---
class ConfigContext:
    """
    Immutable Configuration Context designed to isolate running execution parameters
    across threads or concurrent backtest variants, preventing global variable pollution.
    """
    def __init__(self, **kwargs):
        # Automatically capture all package-level parameters as instance defaults
        g = globals()
        for k, v in g.items():
            if not k.startswith("__") and k not in ["os", "datetime", "timezone", "load_dotenv", "get_env_stripped", "Settings", "_settings"]:
                # Ensure we do not copy classes or types
                if not isinstance(v, type):
                    setattr(self, k, v)
        # Apply overrides
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get(self, key, default=None):
        return getattr(self, key, default)
