import os
from dotenv import load_dotenv
load_dotenv()

# --- Mode & environment ---
MODE = os.getenv("MODE", "paper").lower()
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

# --- Account ---
INITIAL_EQUITY = 100.0
RISK_PER_TRADE = 0.01            # fraction of equity risked per trade
MAX_CONCURRENT_POSITIONS = 10
DRAWDOWN_LIMIT = 0.5             # stop if equity <= 50% of peak
TOTAL_ROI_LIMIT = 1.0            # stop if ROI >= +100%

# --- Fees ---
MAKER_FEE = 0.0002               # 0.02%
TAKER_FEE = 0.0006               # 0.06%

# --- Assets ---
ASSETS = [
    "SOLUSDT", "DOGEUSDT", "XRPUSDT", "ADAUSDT",
    "SUIUSDT", "LINKUSDT", "AVAXUSDT", "HYPEUSDT", "ENAUSDT"
]
BTC_SYMBOL = "BTCUSDT"           # will be added to simulation automatically

# --- Initial prices (for simulation) ---
BASE_PRICES = {
    "SOLUSDT": 25.0, "DOGEUSDT": 0.07, "XRPUSDT": 0.50,
    "ADAUSDT": 0.30, "SUIUSDT": 0.80, "LINKUSDT": 12.0,
    "AVAXUSDT": 18.0, "HYPEUSDT": 10.0, "ENAUSDT": 0.60,
    "BTCUSDT": 60000.0,
}

LEVERAGE_LIMITS = {
    "SOLUSDT": 100.0, "DOGEUSDT": 50.0, "XRPUSDT": 100.0,
    "ADAUSDT": 75.0, "SUIUSDT": 50.0, "LINKUSDT": 75.0,
    "AVAXUSDT": 50.0, "HYPEUSDT": 20.0, "ENAUSDT": 20.0,
    "BTCUSDT": 125.0,
}

# --- Simulation parameters ---
SIM_SIGMA = 0.0002               # tick volatility (log‑return)
SIM_SIGNAL_STRENGTH = 0.0002    # how much imbalance moves price
SIM_IMBALANCE_NOISE = 0.02       # random walk of imbalance

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
MIN_CONFIDENCE = 0.66            # minimum probability to trade
MIN_IMBALANCE = 0.05             # only trade if |imbalance| > this
TREND_STRENGTH_MIN = 0.3         # DRT minimum
# Win/Loss barriers (symmetric 1:1)
TP_MOVE = 0.015                 # 0.15% take‑profit
SL_MOVE = 0.003                 # 0.15% stop‑loss