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
LOG_REJECTIONS = False            # Toggle rejection logs in console
LOG_SIGNALS = False               # Toggle signal logs in console
MAX_CONCURRENT_POSITIONS = 50
DRAWDOWN_LIMIT = 0.5             # stop if equity <= 50% of peak
TOTAL_ROI_LIMIT = 1.0            # stop if ROI >= +100%

# --- Fees ---
MAKER_FEE = 0.0002               # 0.02%
TAKER_FEE = 0.0006               # 0.06%

# --- Assets ---
ASSETS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "TAOUSDT", "BNBUSDT",
    "HYPEUSDT", "DOGEUSDT", "TRXUSDT", "ZECUSDT", "SUIUSDT", "WLDUSDT",
    "ADAUSDT", "NEARUSDT", "AVAXUSDT", "LINKUSDT", "XLMUSDT", "BCHUSDT",
    "LTCUSDT", "ENAUSDT", "TRUMPUSDT", "AAVEUSDT", "UNIUSDT", "XMRUSDT",
    "GRTUSDT", "HBARUSDT", "NEOUSDT", "POLUSDT", "SHIBUSDT", "CROUSDT",
    "PEPEUSDT", "ASTERUSDT", "DOTUSDT", "ICPUSDT", "ONDOUSDT", "BGBUSDT", "PIUSDT"
]
BTC_SYMBOL = "BTCUSDT"

# --- Initial prices (for simulation) ---
BASE_PRICES = {
    "BTCUSDT": 60000.0, "ETHUSDT": 3000.0, "SOLUSDT": 100.0, "XRPUSDT": 0.50,
    "TAOUSDT": 300.0, "BNBUSDT": 400.0, "HYPEUSDT": 10.0, "DOGEUSDT": 0.10,
    "TRXUSDT": 0.10, "ZECUSDT": 30.0, "SUIUSDT": 1.0, "WLDUSDT": 2.0,
    "ADAUSDT": 0.30, "NEARUSDT": 4.0, "AVAXUSDT": 30.0, "LINKUSDT": 15.0,
    "XLMUSDT": 0.10, "BCHUSDT": 400.0, "LTCUSDT": 80.0, "ENAUSDT": 0.60,
    "TRUMPUSDT": 10.0, "AAVEUSDT": 100.0, "UNIUSDT": 7.0, "XMRUSDT": 150.0,
    "GRTUSDT": 0.20, "HBARUSDT": 0.08, "NEOUSDT": 10.0, "POLUSDT": 0.50,
    "SHIBUSDT": 0.00002, "CROUSDT": 0.10, "PEPEUSDT": 0.00001, "ASTERUSDT": 0.05,
    "DOTUSDT": 7.0, "ICPUSDT": 10.0, "ONDOUSDT": 0.80, "BGBUSDT": 1.0, "PIUSDT": 30.0
}

LEVERAGE_LIMITS = {
    "BTCUSDT": 150.0, "ETHUSDT": 150.0, "SOLUSDT": 100.0, "XRPUSDT": 125.0,
    "TAOUSDT": 50.0, "BNBUSDT": 75.0, "HYPEUSDT": 75.0, "DOGEUSDT": 75.0,
    "TRXUSDT": 75.0, "ZECUSDT": 75.0, "SUIUSDT": 75.0, "WLDUSDT": 75.0,
    "ADAUSDT": 75.0, "NEARUSDT": 75.0, "AVAXUSDT": 75.0, "LINKUSDT": 75.0,
    "XLMUSDT": 75.0, "BCHUSDT": 75.0, "LTCUSDT": 75.0, "ENAUSDT": 75.0,
    "TRUMPUSDT": 75.0, "AAVEUSDT": 75.0, "UNIUSDT": 75.0, "XMRUSDT": 50.0,
    "GRTUSDT": 75.0, "HBARUSDT": 75.0, "NEOUSDT": 75.0, "POLUSDT": 50.0,
    "SHIBUSDT": 75.0, "CROUSDT": 25.0, "PEPEUSDT": 75.0, "ASTERUSDT": 50.0,
    "DOTUSDT": 75.0, "ICPUSDT": 50.0, "ONDOUSDT": 50.0, "BGBUSDT": 50.0, "PIUSDT": 50.0
}

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
TP_MOVE = 0.0015                 # 0.3% take‑profit
SL_MOVE = 0.001                 # 0.3% stop‑loss
MAX_ENTRY_SLIPPAGE = 0.001     # 0.05% max slippage for entry

# --- Scoring Thresholds ---
RSI_LONG = 45.0
RSI_SHORT = 55.0
TREND_15M_MIN = 0.0001

# --- Restriction Toggles (Naked Baseline) ---
RESTRICT_DRT = False
RESTRICT_IMBALANCE = False
RESTRICT_CONFIDENCE = False
RESTRICT_DIRECTIONAL_SANITY = False
RESTRICT_RSI = False
RESTRICT_MACD = False
RESTRICT_EMA = False
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
