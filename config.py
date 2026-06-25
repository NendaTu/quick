import os
from dotenv import load_dotenv
load_dotenv()

# --- Mode & environment ---
MODE = os.getenv("MODE", "paper").lower()
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

# --- Account ---
INITIAL_EQUITY = 1000.0
RISK_PER_TRADE = 0.002           # fraction of equity risked per trade
LOG_REJECTIONS = False            # Toggle rejection logs in console
LOG_SIGNALS = False               # Toggle signal logs in console
MAX_CONCURRENT_POSITIONS = 50
DRAWDOWN_LIMIT = 0.5             # stop if equity <= 50% of peak
TOTAL_ROI_LIMIT = 0.1            # stop if ROI >= +10% (+100 PnL)
MAX_TRADES_LIMIT = 500           # stop after 500 trades
MAX_DURATION = 14400             # stop after 4 hours (seconds)

# --- Execution ---
ENTRY_ORDER_TYPE = "limit"       # "market" or "limit"
TP_ORDER_TYPE = "limit"          # "market" or "limit"
SL_ORDER_TYPE = "limit"          # "market" or "limit"
SL_DISASTER_BUFFER = 0.001       # 0.1% move past SL price before Market backup
TRADE_TTL_SECONDS = 180          # 3 minute limit
EXPECTED_SLIPPAGE = 0.0005       # 0.05% expected slippage for math
LIMIT_CHASE_TIMEOUT = 10.0       # seconds

# --- Fees ---
MAKER_FEE = 0.0002               # 0.02%
TAKER_FEE = 0.0006               # 0.06%

# --- Assets ---
ASSETS_COUNT = 100
ASSET_OMITTED = ["BTCUSDT"]      # BTC used for global confluence, not trading
BTC_SYMBOL = "BTCUSDT"

# --- Indicator windows (number of ticks, each tick = ~0.2s) ---
INDICATOR_PRICE_HISTORY = 500    # max ticks to keep
RSI_PERIOD = 14
ATR_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_SHORT = 9
EMA_LONG = 21
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0

# --- Confluence timeframes (converted to ticks) ---
TICK_SECONDS = 0.2
# We approximate candles: 15m, 1H, 4H, 1D in ticks
TF_TICKS = {
    "15m": int(15 * 60 / TICK_SECONDS),   # 4500
    "1H": int(60 * 60 / TICK_SECONDS),    # 18000
    "4H": int(240 * 60 / TICK_SECONDS),   # 72000
    "1D": int(1440 * 60 / TICK_SECONDS),  # 432000
}

# --- Model thresholds ---
MIN_CONFIDENCE = 0.66             # minimum probability to trade
MIN_IMBALANCE = 0.033             # only trade if |imbalance| > this
TREND_STRENGTH_MIN = 0.1         # DRT minimum
# Win/Loss barriers (symmetric 1:1)
TP_MOVE = 0.008                  # 0.8% take‑profit
SL_MOVE = 0.004                  # 0.4% stop‑loss
MAX_ENTRY_SLIPPAGE = 0.001     # 0.05% max slippage for entry

# --- Strategy Hardening ---
TARGET_NET_ROE = 0.05            # 5% Net ROE target
RSI_BUY_FLOOR = 15.0             # Reject Buys if RSI < this
RSI_SHORT_CEILING = 80.0         # Reject Shorts if RSI > this
REENTRY_COOLDOWN = 60.0          # Seconds to wait after exit before re-entering same asset
USE_DYNAMIC_TARGETS = True       # Calculate TP/SL based on leverage and TARGET_NET_ROE
USE_ATR_SL = True                # Use ATR for stop loss
ATR_SL_MULT = 1.5                # ATR multiplier for SL
ATR_MIN = 0.0001                 # Minimum ATR to avoid low-volatility assets
VOL_PCT_MIN = 0.05               # Minimum relative volume
MAX_SPREAD_PCT = 0.002           # Max spread % (0.2%)

# --- Advanced Strategy Features ---
CONTRARIAN_GLOBAL = False        # Flip final order direction (BUY <-> SELL)
CONTRARIAN_FILTER = False        # Flip filter logic (requires CONTRARIAN_GLOBAL=True)
USE_BREAKEVEN_TRIGGER = True     # Move SL to entry after price moves halfway to TP
BREAKEVEN_ROI_THRESHOLD = 0.025  # 2.5% ROE threshold for breakeven
USE_ATR_CAPPED_TP = True         # Cap dynamic TP by 15m ATR to ensure reachability
USE_DRT_VELOCITY = True          # Ensure pulse is accelerating in trade direction
USE_ADAPTIVE_RSI = True          # Tighten RSI filters unless momentum is high
RSI_TIGHT_LONG = 25.0
RSI_TIGHT_SHORT = 75.0

# --- Scoring Thresholds ---
RSI_LONG = 40.0
RSI_SHORT = 60.0
TREND_15M_MIN = 0.0001

# --- Timeframes ---
AVAILABLE_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1H", "4H", "1D"]
INDICATOR_TIMEFRAMES = {
    "rsi": "1m",
    "macd": "1m",
    "ema": "1m",
    "atr": "1m",
    "drt_slow": "15m",
    "drt_fast": "5m",
}

# --- Restriction Toggles (Naked Baseline) ---
RESTRICT_DRT = False
RESTRICT_IMBALANCE = False
RESTRICT_CONFIDENCE = False
RESTRICT_DIRECTIONAL_SANITY = False
RESTRICT_RSI = True
RESTRICT_MACD = False
RESTRICT_15M_TREND = False
RESTRICT_SUPERTREND = False
RESTRICT_ATR = False
RESTRICT_VOL_PCT = False
RESTRICT_SPREAD = False
RESTRICT_BTC_CONFLUENCE = False
RESTRICT_ASSET_CONFLUENCE = False
RESTRICT_LIQUIDITY = False
RESTRICT_SLIPPAGE = False
RESTRICT_MIN_VAL = False
RESTRICT_SCORE = False

# --- BTC Confluence Thresholds ---
BTC_CONF_15M_MIN = 0.0002
BTC_CONF_1H_MIN = 0.0002
