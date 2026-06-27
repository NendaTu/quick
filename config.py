import os
from dotenv import load_dotenv
load_dotenv()

# --- Mode & Environment ---
# Sets whether the bot runs in "paper" (simulated) or "live" (real funds) mode.
MODE = os.getenv("MODE", "paper").lower()

# Exchange credentials sourced from your .env file. Required for both paper and live.
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

# --- Account ---
# The simulated starting balance used for all PnL and risk calculations.
INITIAL_EQUITY = 15.0

# The maximum fraction of your total balance you are willing to lose on a single trade.
# Example: 0.002 means you risk 0.2% (2 USDT on a 1000 USDT balance) per trade.
RISK_PER_TRADE = 0.05

# If True, the console will show every trade that was rejected by the filters and why.
LOG_REJECTIONS = False

# If True, the console will show every signal the bot generates before it tries to enter.
LOG_SIGNALS = False

# If True, the bot will print a periodic summary of performance to the console.
SHOW_PERIODIC_SUMMARY = True

# How often (in seconds) the periodic summary should be printed.
SUMMARY_INTERVAL_SECONDS = 15

# The maximum number of trades allowed to be open at the same time across all assets.
MAX_CONCURRENT_POSITIONS = 50

# Safety trigger: Stop the bot entirely if balance drops to this percentage of its all-time high.
# 0.5 means stop at 50% drawdown.
DRAWDOWN_LIMIT = 0.8

# Target goal: Stop the bot once it gains this percentage of the starting equity.
# 0.1 means stop after a 10% total profit.
TOTAL_ROI_LIMIT = 1

# Minimum cumulative indicator score (from RSI, MACD, etc.) required to trigger a trade.
# Higher values increase selectivity (quality) but reduce trade frequency.
MIN_REQUIRED_SCORE = 1.5

# Stop the bot after it has completed this many total trades (wins + losses).
MAX_TRADES_LIMIT = 5000

# Time limit: Stop the bot after this many seconds have elapsed. (14400s = 4 hours)
MAX_DURATION = 14400

# --- Execution ---
# Order type for entries: "limit" to earn Maker fees (may not fill), "market" to fill instantly.
ENTRY_ORDER_TYPE = "limit"

# Order type for Take-Profit exits. "limit" is recommended to maximize net profit.
TP_ORDER_TYPE = "limit"

# Order type for Stop-Loss. "limit" enables "Soft-Stop" (Maker exit), "market" is safer but costs more.
SL_ORDER_TYPE = "limit"

# If SL_ORDER_TYPE is "limit", this is the safety buffer. If price moves this % past our limit
# without filling, the bot fires a Market order to exit immediately. (0.001 = 0.1%)
SL_DISASTER_BUFFER = 0.001

# --- TTL (Time-to-Live) Settings ---
# Toggle for force-exiting stagnant trades after a certain duration.
USE_TTL = True

# The number of candles of the ACTIVE_TIMEFRAME to wait before force-exiting.
# Example: 3 on a 1m timeframe = 180s. 3 on a 5m timeframe = 900s.
TTL_CANDLE_MULTIPLIER = 15

# Estimated cost of price movement against us during execution. Factored into fee/target math.
EXPECTED_SLIPPAGE = 0.001

# How long (in seconds) the bot will wait for a "limit" entry to fill before converting it to "market".
LIMIT_CHASE_TIMEOUT = 10.0

# --- Fees ---
# Standard Bitget Maker/Taker fee rates. Used for Net ROE and position sizing math.
MAKER_FEE = 0.0002               # 0.02%
TAKER_FEE = 0.0006               # 0.06%

# --- Assets ---
# The number of top-volume assets the bot will monitor simultaneously.
ASSETS_COUNT = 200

# How often (in hours) the bot should refresh the list of top-volume assets from the exchange.
# Assets are cached in the local database to speed up restarts.
ASSET_REDISCOVERY_HOURS = 6.0

# Specific assets to exclude from trading (e.g., BTC which is used for global confluence).
ASSET_OMITTED = ["BTCUSDT"]
BTC_SYMBOL = "BTCUSDT"

# --- Indicator Windows (Technical Settings) ---
# How many "ticks" (0.2s updates) of price history to keep in memory for technical analysis.
INDICATOR_PRICE_HISTORY = 500

# Standard periods for calculating technical indicators (RSI, ATR, MACD, EMA).
RSI_PERIOD = 14
ATR_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_SHORT = 9
EMA_LONG = 21
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0

# --- Timeframes & Pattern Settings ---
# Primary timeframe used for trading signals and entry analysis.
ACTIVE_TIMEFRAME = "5m"

# Fair Value Gap (FVG) detection settings.
FVG_TIMEFRAME = "15m"
FVG_HISTORY_DEPTH = 50

# --- Confluence Timeframes ---
# Time duration of a single simulation update loop.
TICK_SECONDS = 0.2

# Pre-calculated tick counts for higher timeframes (15m, 1H, etc.).
TF_TICKS = {
    "15m": int(15 * 60 / TICK_SECONDS),
    "1H": int(60 * 60 / TICK_SECONDS),
    "4H": int(240 * 60 / TICK_SECONDS),
    "1D": int(1440 * 60 / TICK_SECONDS),
}

# --- Model Thresholds ---
# Minimum required signal probability (0.0 to 1.0) to consider a trade.
MIN_CONFIDENCE = 0.66

# Minimum order book imbalance (bid vs ask pressure) required to trade.
MIN_IMBALANCE = 0.033

# Minimum trend strength (DRT pulse) required. 0.1 means price must be moving.
TREND_STRENGTH_MIN = 0.1

# The target % price move for profit.
# Works in conjunction with USE_DYNAMIC_TARGETS:
# - If True: This acts as the absolute minimum profit "floor".
# - If False: This is the exact fixed profit target for every trade.
TP_MOVE = 0.015                  # 0.8%

# The target % price move for the stop loss.
# Works in conjunction with USE_ATR_SL:
# - If True: This is only used as a fallback if ATR data is unavailable.
# - If False: This is the exact fixed stop distance for every trade.
SL_MOVE = 0.005                  # 0.4%

# Maximum allowed difference between requested entry price and fill price for "market" entries.
MAX_ENTRY_SLIPPAGE = 0.001

# --- Strategy Hardening ---
# The compounding goal for each trade (Return on Equity).
# Works with USE_DYNAMIC_TARGETS to widen the TP move enough to cover fees and hit this net % gain.
TARGET_NET_ROE = 0.20            # 20% Net ROE target

# Protective floors/ceilings for RSI. Prevents buying "falling knives" or shorting "moons".
# Dependency: Works only if RESTRICT_RSI = True.
RSI_BUY_FLOOR = 15.0
RSI_SHORT_CEILING = 80.0

# Minimum wait time (seconds) after exiting an asset before the bot can enter it again.
REENTRY_COOLDOWN = 60.0

# Toggle for "Net ROE" logic. If True, targets scale based on leverage to hit TARGET_NET_ROE.
USE_DYNAMIC_TARGETS = True

# Toggle for volatility-aware stops. If True, SL distance widens/narrows based on market noise.
USE_ATR_SL = True

# Multiplier for ATR stop distance. Higher = wider stops, lower position quantity.
ATR_SL_MULT = 1.5

# Minimum volatility (ATR) required. Prevents trading completely flat "zombie" assets.
ATR_MIN = 0.0001

# Minimum relative volume required compared to recent average.
VOL_PCT_MIN = 0.05

# Maximum allowed bid/ask spread %. Prevents trading assets with expensive "gaps" in the book.
MAX_SPREAD_PCT = 0.002

# Toggle for high-volatility risk reduction. If True, reduces position size during extreme noise.
USE_VOL_ADJUSTED_RISK = True

# ATR level above which the bot considers the market "too volatile" and reduces risk.
# 0.002 means if 1m ATR is > 0.2% of price, risk is halved.
ATR_VOL_THRESHOLD = 0.002

# The multiplier applied to RISK_PER_TRADE when ATR exceeds ATR_VOL_THRESHOLD.
REDUCED_RISK_FRACTION = 0.5

# --- Advanced Strategy Features ---
# If True, the bot flips its logic (buys when signals say sell, and vice versa).
CONTRARIAN_GLOBAL = False

# Dependency: If CONTRARIAN_GLOBAL is True, this determines if technical filters are also flipped.
CONTRARIAN_FILTER = False

# Risk protection: Moves the Stop-Loss to entry price once the trade is significantly in profit.
USE_BREAKEVEN_TRIGGER = True

# ROE level required to activate the breakeven move. (0.025 = 2.5% gain)
BREAKEVEN_ROI_THRESHOLD = 0.20

# Extra profit buffer added to the breakeven move (covers fees + this ROE profit).
BREAKEVEN_PROFIT_BUFFER = 0.05

# Logic to cap Take-Profit by 15m volatility to ensure the target is "reachable".
USE_ATR_CAPPED_TP = False

# Momentum acceleration check: Buy only if 1m trend is stronger than 5m trend.
USE_DRT_VELOCITY = False

# Automatically tightens RSI entry windows unless high-timeframe momentum is present.
USE_ADAPTIVE_RSI = True
RSI_TIGHT_LONG = 25.0
RSI_TIGHT_SHORT = 75.0

# Toggle for TP relaxation. If True, the bot accepts lower ROE targets during low-volatility/flat trends.
USE_TP_RELAXATION = True

# The lower ROE target (Return on Equity) used when relaxation is active.
RELAXED_ROE_TARGET = 0.03 # 3% instead of 5%

# The DRT pulse threshold (closeness to 0.5) to trigger relaxation.
# 0.05 means if |DRT - 0.5| < 0.05 (near flat), use the relaxed target.
TP_RELAXATION_THRESHOLD = 0.05

# --- Scoring Thresholds ---
# Bases for indicator scoring. RSI < RSI_LONG gets +1 point for "Buy" score.
RSI_LONG = 40.0
RSI_SHORT = 60.0
TREND_15M_MIN = 0.0001

# --- Timeframes ---
# List of timeframes used for Multi-Timeframe (MTF) analysis.
AVAILABLE_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1H", "4H", "1D"]

# Assignment of specific indicators to their respective analysis timeframes.
# Dynamic: rsi, macd, ema, and atr track the ACTIVE_TIMEFRAME.
INDICATOR_TIMEFRAMES = {
    "rsi": ACTIVE_TIMEFRAME,
    "macd": ACTIVE_TIMEFRAME,
    "ema": ACTIVE_TIMEFRAME,
    "atr": ACTIVE_TIMEFRAME,
    "drt_slow": "15m",
    "drt_fast": "5m",
}

# --- Restriction Toggles (Hard Gates) ---
# Each toggle, if set to True, turns a specific filter into a "Hard Gate".
# If the condition is not met, the signal is discarded regardless of other indicator scores.
RESTRICT_DRT = False
RESTRICT_IMBALANCE = True
RESTRICT_CONFIDENCE = False
RESTRICT_DIRECTIONAL_SANITY = False # Forces score direction to match DRT trend pulse.
RESTRICT_RSI = True
RESTRICT_RSI_SHORT_CEILING = True   # Specific gate for the Short ceiling safety check.
RESTRICT_MACD = False
RESTRICT_15M_TREND = False
RESTRICT_SUPERTREND = False
RESTRICT_ATR = False
RESTRICT_VOL_PCT = False
RESTRICT_SPREAD = False
RESTRICT_BTC_CONFLUENCE = False     # Multi-timeframe BTC trend alignment gate.
RESTRICT_ASSET_CONFLUENCE = False   # Asset 15m momentum alignment gate.
RESTRICT_LIQUIDITY = True
RESTRICT_SLIPPAGE = True
RESTRICT_MIN_VAL = True            # Minimum USDT trade value enforcement.
RESTRICT_SCORE = False               # Enforces a minimum cumulative score before trading.

# BTC Global Momentum Gate: Blocks counter-trend trades during significant BTC flushes/moons.
# Dependency: Works with BTC_MOMENTUM_THRESHOLD.
RESTRICT_BTC_MOMENTUM = True

# Logic to subtract estimated fees from the risk capacity during position sizing.
# Ensures that (Loss + Fees) stays within the RISK_PER_TRADE budget.
FEE_AWARE_SIZING = True

# --- BTC Confluence Thresholds ---
# Specific momentum thresholds (decimal %) for macro trend alignment filters.
BTC_CONF_15M_MIN = 0.0002
BTC_CONF_1H_MIN = 0.0002
BTC_MOMENTUM_THRESHOLD = 0.001   # Threshold for RESTRICT_BTC_MOMENTUM gate.

# --- Multi-Stage Exit Strategy ---
# Options: "BE+TP" (Standard) or "BE+TP1+TP2" (Multi-stage)
# Only respected if USE_BREAKEVEN_TRIGGER is True.
EXIT_STRATEGY = "BE+TP1+TP2"

# Ratio of the position to close at the first Take-Profit level (TP1).
TP1_QTY_RATIO = 0.5

# Distance of TP1 from the Breakeven price, expressed as a fraction of the distance between BE and TP2.
# 0.5 means TP1 is exactly halfway between the Breakeven price and the final Take-Profit (TP2).
TP1_BUFFER_PCT = 0.5
