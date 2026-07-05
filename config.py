import os
from dotenv import load_dotenv
load_dotenv()

# --- Mode & Environment ---
# Sets whether the bot runs in "paper" (simulated) or "live" (real funds) mode.
MODE = os.getenv("MODE", "paper").lower()

# Exchange credentials sourced from your .env file.
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

# --- Account & Risk ---
# The simulated starting balance used for all PnL and risk calculations.
INITIAL_EQUITY = 15.0

# [TECH-001] Compound every trade via 100% reinvestment.
REINVESTMENT_PERCENTAGE = 1.0

# Maximum fraction of total balance risked per single trade (0.005 = 0.5%).
RISK_PER_TRADE = 0.0667

# Maximum number of concurrent positions allowed.
MAX_CONCURRENT_POSITIONS = 100

# Stop bot if balance drops below this fraction of ATH (0.5 = 50% drawdown).
DRAWDOWN_LIMIT = 0.5

# Stop bot if total ROI reaches this fraction (1.0 = 100% profit).
TOTAL_ROI_LIMIT = 10.0

# Stop bot after this many total trades.
MAX_TRADES_LIMIT = 5000

# Stop bot after this many seconds elapsed (86400 = 24 hours).
MAX_DURATION = 86400

# --- Assets ---
# Number of top-volume assets to monitor simultaneously.
ASSETS_COUNT = 250

# Refresh top assets list every N hours.
ASSET_REDISCOVERY_HOURS = 6.0

# Assets to exclude from trading.
ASSET_OMITTED = ["BTCUSDT"]
BTC_SYMBOL = "BTCUSDT"

# --- Execution ---
# Order type for entries, Take-Profits, and Stop-Losses.
ENTRY_ORDER_TYPE = "limit"
TP_ORDER_TYPE = "limit"
SL_ORDER_TYPE = "limit"

# Safety buffer for limit stop-losses (0.001 = 0.1%).
SL_DISASTER_BUFFER = 0.001

# How long (s) to wait for a limit entry to fill before converting to market.
LIMIT_CHASE_TIMEOUT = 10.0

# --- Strategy Hardening ---
# Toggle for online LearningModel training.
USE_ONLINE_LEARNING = False

# Target Return on Equity (ROE) per trade (0.20 = 20%).
TARGET_NET_ROE = 0.20

# Minimum wait time (seconds) after exiting an asset before re-entry.
REENTRY_COOLDOWN = 60.0

# TP Relaxation: Accepts lower ROE targets during flat trends.
USE_TP_RELAXATION = True
RELAXED_ROE_TARGET = 0.03
TP_RELAXATION_THRESHOLD = 0.05

# Time-to-Live (TTL): Force-exit stagnant trades after N candles.
USE_TTL = False
TTL_CANDLE_MULTIPLIER = 15

# Breakeven Protection: Move SL to entry after ROE threshold hit.
USE_BREAKEVEN_TRIGGER = False
BREAKEVEN_ROI_THRESHOLD = 0.20
BREAKEVEN_PROFIT_BUFFER = 0.05

# Exit Strategy: "BE+TP" or "BE+TP1+TP2".
EXIT_STRATEGY = "BE+TP1+TP2"
TP1_QTY_RATIO = 0.5
TP1_BUFFER_PCT = 0.5

# Contrarian Settings: Flip logic directions.
CONTRARIAN_GLOBAL = False
CONTRARIAN_FILTER = False

# Risk Protection: Momentum acceleration check.
USE_DRT_VELOCITY = False

# Adaptive RSI Settings.
USE_ADAPTIVE_RSI = False

# ATR Capping for Take-Profit.
USE_ATR_CAPPED_TP = False

# Volatility Adjusted Risk.
USE_VOL_ADJUSTED_RISK = False

# BTC Momentum Gate.
RESTRICT_BTC_MOMENTUM = False
BTC_MOMENTUM_THRESHOLD = 0.001

# Multi-timeframe trend alignment gates.
RESTRICT_BTC_CONFLUENCE = False
RESTRICT_ASSET_CONFLUENCE = False
BTC_CONF_15M_MIN = 0.0002
BTC_CONF_1H_MIN = 0.0002

# Trend scoring thresholds.
TREND_15M_MIN = 0.0001

# Indicator Hard Gates.
RESTRICT_DRT = False
RESTRICT_CONFIDENCE = False
RESTRICT_DIRECTIONAL_SANITY = False
RESTRICT_RSI = False
RESTRICT_RSI_SHORT_CEILING = False
RESTRICT_MACD = False
RESTRICT_15M_TREND = False
RESTRICT_SUPERTREND = False
RESTRICT_ATR = False
RESTRICT_VOL_PCT = False
RESTRICT_SPREAD = False
RESTRICT_LIQUIDITY = False
RESTRICT_SLIPPAGE = False
RESTRICT_SCORE = False

# Minimum confidence required to trade.
MIN_CONFIDENCE = 0.66

# Multi-Timeframe (MTF) analysis configuration.
ACTIVE_TIMEFRAME = "1m"
AVAILABLE_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1H", "4H", "1D"]

# --- Global Restriction Toggles ---
RESTRICT_IMBALANCE = True
RESTRICT_HTF_BIAS = True
RESTRICT_VOLUME_INFLUX = True
RESTRICT_MIN_VAL = True
RESTRICT_STRUCTURE = False # [OP-007] Set to True to require BOS/MSS for entry

# --- Logging & UI ---
LOG_REJECTIONS = False
LOG_SIGNALS = False
SHOW_PERIODIC_SUMMARY = True
SUMMARY_INTERVAL_SECONDS = 15

# --- Simulator & Technical Analysis Internal Settings ---
TICK_SECONDS = 0.2
INDICATOR_PRICE_HISTORY = 500
MAKER_FEE = 0.0002
TAKER_FEE = 0.0006
EXPECTED_SLIPPAGE = 0.001
MAX_ENTRY_SLIPPAGE = 0.001
MAX_SPREAD_PCT = 0.002
FEE_AWARE_SIZING = True
BTC_REALTIME_CONFLUENCE = True
SESSION_MULTIPLIER = 1.5
