import os
from datetime import datetime
import pytz
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

# --- Mode & Environment ---
# MODE: Determines whether the trading bot runs in paper simulation, exchange demo, or exchange live environment.
# When set to "live" or "demo", expect real-time WebSockets and execution order dispatching, while "paper" runs local risk matching.
MODE = get_env_stripped("MODE", "paper").lower()

# BITGET_API_KEY: Configures your live Bitget exchange API key credential.
# Expect successful connection and private order capabilities in live mode when a valid key is provided.
BITGET_API_KEY = get_env_stripped("BITGET_API_KEY")

# BITGET_SECRET_KEY: Configures your live Bitget exchange secret key credential.
# Expect authentication to succeed on private REST and WebSocket channels when correctly configured.
BITGET_SECRET_KEY = get_env_stripped("BITGET_SECRET_KEY")

# BITGET_PASSPHRASE: Configures your live Bitget exchange account passphrase.
# Expect V2 API signatures to successfully authenticate private execution endpoints.
BITGET_PASSPHRASE = get_env_stripped("BITGET_PASSPHRASE")

# BITGET_API_KEY_DEMO: Configures your Bitget exchange paper trading (Demo) API key credential.
# Expect private demo order routing to function correctly on Bitget's V2 demo contracts endpoints.
BITGET_API_KEY_DEMO = get_env_stripped("BITGET_API_KEY_DEMO") or BITGET_API_KEY

# BITGET_SECRET_KEY_DEMO: Configures your Bitget exchange paper trading (Demo) secret key credential.
# Expect demo mode private requests to sign successfully and bypass standard live balances.
BITGET_SECRET_KEY_DEMO = get_env_stripped("BITGET_SECRET_KEY_DEMO") or BITGET_SECRET_KEY

# BITGET_PASSPHRASE_DEMO: Configures your Bitget exchange paper trading (Demo) account passphrase.
# Expect demo mode private WebSocket listeners and order dispatching to authenticate seamlessly.
BITGET_PASSPHRASE_DEMO = get_env_stripped("BITGET_PASSPHRASE_DEMO") or BITGET_PASSPHRASE


# --- Account & Risk ---
# USE_VIRTUAL_BALANCE: Toggles if the live/demo modes use the simulated INITIAL_EQUITY instead of your real balance.
# When enabled, expect position sizes to calculate against a virtual balance to avoid real capital exposure during early runs.
USE_VIRTUAL_BALANCE = False

# INITIAL_EQUITY: Sets the starting capital allocated for virtual balance, simulation, and backtesting.
# Expect all subsequent PnL growth curves and compounding size calculations to start from this baseline amount.
INITIAL_EQUITY = 40.0

# REINVESTMENT_PERCENTAGE: Configures the fraction of net profits that are reinvested into subsequent position sizes (1.0 = 100%).
# When set close to 1.0, expect rapid geometric compounding growth of your position size as equity grows.
REINVESTMENT_PERCENTAGE = 1.0

# RISK_PER_TRADE: Configures the maximum fraction of your total balance to risk on any single trade (0.01 = 1%).
# Expect position sizing models to automatically reduce the contract size when the stop loss distance is wider.
RISK_PER_TRADE = 0.01

# MAX_CONCURRENT_POSITIONS: Limits the maximum number of positions that can be open simultaneously.
# Expect the trading loop to automatically ignore any new entry signals once this concurrent limit is reached.
MAX_CONCURRENT_POSITIONS = 1000

# DRAWDOWN_LIMIT: Shuts down the bot if the account equity drops below this fraction of the peak equity (0.25 = 25% drawdown).
# Expect the system to immediately halt and protect remaining capital if a major losing streak occurs.
DRAWDOWN_LIMIT = 0.25

# TOTAL_ROI_LIMIT: Shuts down the bot if your account equity reaches this return on investment multiple (1000.0 = 100000% profit).
# Expect the session to cleanly terminate and secure profits once your predefined capital target is hit.
TOTAL_ROI_LIMIT = 1000.0

# MAX_TRADES_LIMIT: Caps the maximum number of completed trades allowed before the bot halts.
# Expect the execution engine to stop taking new setups and shut down once this count is completed.
MAX_TRADES_LIMIT = 5000

# MAX_DURATION: Restricts the total execution runtime of the bot in seconds (86400 = 24 hours).
# Expect the bot to finalize its trading loops and exit gracefully once this duration elapsed.
MAX_DURATION = 86400


# --- Assets ---
# ASSETS_COUNT: Controls the maximum number of high-volume assets to discover and trade.
# Expect the system to dynamically select and monitor the top-N liquid assets on the exchange.
ASSETS_COUNT = 250

# ASSET_REDISCOVERY_HOURS: Configures the refresh interval in hours for updating the discovered assets list.
# Expect the bot to periodically scan the exchange and update the list of traded assets when this interval ends.
ASSET_REDISCOVERY_HOURS = 6.0

# ASSET_OMITTED: Defines a blacklist of specific symbols that are excluded from trading.
# Expect the discovery loop to skip these assets (e.g. BTCUSDT) to avoid trading highly correlated majors.
ASSET_OMITTED = ["BTCUSDT"]

# BTC_SYMBOL: Defines the canonical reference symbol used for market confluence and trend scoring.
# Expect this symbol to be queried and monitored constantly to determine global market direction.
BTC_SYMBOL = "BTCUSDT"


# --- Acquisition & Timeframes ---
# MAX_START_DATE: Sets the earliest date boundary for downloading historical backtest candles.
# Expect historical data queries to start fetching candles starting exactly from this date.
MAX_START_DATE = datetime(2022, 6, 1, tzinfo=pytz.UTC)

# MAX_END_DATE: Sets the latest date boundary for downloading historical backtest candles.
# Expect backtests and data downloads to stop fetching candles once this date is reached.
MAX_END_DATE = datetime(2026, 6, 1, tzinfo=pytz.UTC)

# ACTIVE_TIMEFRAME: Defines the primary timeframe used for candle execution and entry signals.
# Expect strategy loops and indicator updates to synchronize on this candle timeframe (e.g. 1m).
ACTIVE_TIMEFRAME = "1m"

# AVAILABLE_TIMEFRAMES: List of all timeframes loaded and maintained for multi-timeframe analysis.
# Expect indicators to query and build historical buffers for each timeframe specified in this list.
AVAILABLE_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1H", "4H", "1D"]

# TF_SECONDS: A dictionary mapping timeframe strings to their corresponding duration in seconds.
# Expect internal candle closed checkers to use these values to prevent look-ahead bias.
TF_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400, "1D": 86400}


# --- Execution ---
# ENTRY_ORDER_TYPE: Configures the order type used for taking entry positions ("limit" or "market").
# Expect limit entries to execute only at your exact price, while market entries fill instantly.
ENTRY_ORDER_TYPE = "limit"

# TP_ORDER_TYPE: Configures the order type used for posting take-profit exit targets.
# Expect limit take-profits to provide maker fee rebates, while market take-profits fill immediately.
TP_ORDER_TYPE = "limit"

# SL_ORDER_TYPE: Configures the order type used for posting stop-loss protective orders.
# Expect limit stop-losses to exit at your stop price, while market stop-losses fill instantly on trigger.
SL_ORDER_TYPE = "limit"

# SL_DISASTER_BUFFER: Set as a slippage safety cushion percentage past your limit stop-loss.
# Expect the system to trigger a market stop backup if the price crashes past this buffer.
SL_DISASTER_BUFFER = 0.001

# SL_MOVE: Fallback protective stop-loss price distance represented as a fraction of price (0.004 = 0.4%).
# Expect the system to fall back to this stop distance if a strategy fails to calculate an exact stop.
SL_MOVE = 0.004

# TP_MOVE: Fallback profit target price distance represented as a fraction of price (0.008 = 0.8%).
# Expect the system to use this exit distance if a strategy fails to define a logical take-profit level.
TP_MOVE = 0.008

# TARGET_NET_ROE: A target net return on equity placeholder used only by the LearningModel (0.20 = 20%).
# Expect the LearningModel to calculate take-profit prices aiming to achieve this return.
TARGET_NET_ROE = 0.20

# LIMIT_CHASE_TIMEOUT: The maximum duration in seconds to wait for a limit entry order to fill before cancellation.
# Expect unfilled limit entry orders to be canceled and assets unlocked once this timeout ends.
LIMIT_CHASE_TIMEOUT = 10.0


# --- Strategy Hardening ---
# USE_ONLINE_LEARNING: Toggles real-time reinforcement learning weight training for the LearningModel.
# When enabled, expect indicators weights to adapt dynamically on-tick and on-trade based on success.
USE_ONLINE_LEARNING = False

# REENTRY_COOLDOWN: The minimum duration in seconds to wait after exiting an asset before re-entry is permitted.
# Expect subsequent entry signals on the same asset to be ignored during this lockout window.
REENTRY_COOLDOWN = 60.0

# MIN_SCALING_DISTANCE_PCT: The minimum price distance (%) required to trigger a position scale-in (0.005 = 0.5%).
# Expect scale-in attempts to be rejected if the price is too close to your average entry.
MIN_SCALING_DISTANCE_PCT = 0.005

# MAX_ATR_EXPANSION_MULTIPLIER: The maximum allowed volatility ratio cap for the range_sweep_ATR strategy (20.0 = 20x).
# Expect highly over-extended parabolic exhaustion candles exceeding this cap to be cleanly discarded.
MAX_ATR_EXPANSION_MULTIPLIER = 20.0

# MIN_NET_TP_PROFIT_PCT: Minimum expected net profit at TP as a fraction of reserved margin (0.001 = 0.1%).
# Expect "fee trap" trades to be rejected before entry if transaction fees exceed this threshold.
MIN_NET_TP_PROFIT_PCT = 0.001

# USE_TP_RELAXATION: Enables reducing profit targets during low-volatility or flat trends.
# When enabled, expect the take-profit distance to compress to secure smaller profits in flat ranges.
USE_TP_RELAXATION = False

# USE_TTL: Enables time-to-live force-exits to close stagnant trades after a fixed candle count.
# When enabled, expect stagnant positions to close automatically via limit orders after N candles pass.
USE_TTL = False

# TTL_CANDLE_MULTIPLIER: Configures the stagnation threshold represented as a multiple of candles.
# Expect the bot to count this many closed candles of ACTIVE_TIMEFRAME before triggering a TTL exit.
TTL_CANDLE_MULTIPLIER = 15

# USE_BREAKEVEN_TRIGGER: Toggles moving your stop-loss to your entry price after a profit milestone is hit.
# When enabled, expect stop-losses to move to entry once the ROI threshold is successfully reached.
USE_BREAKEVEN_TRIGGER = False

# BREAKEVEN_ROI_THRESHOLD: The net ROI multiple required to trigger a breakeven stop-loss movement (0.20 = 20%).
# Expect your position stop-loss to be adjusted once the trade profit exceeds this threshold.
BREAKEVEN_ROI_THRESHOLD = 0.20

# BREAKEVEN_PROFIT_BUFFER: The small profit cushion added to entry price when moving stop-loss to breakeven.
# Expect this buffer to cover transaction fees so that a breakeven exit results in zero net loss.
BREAKEVEN_PROFIT_BUFFER = 0.05

# EXIT_STRATEGY: Sets take-profit exits configuration (e.g. "BE+TP" or "BE+TP1+TP2" split targets).
# Expect partial exit orders to post on-exchange when "BE+TP1+TP2" is selected.
EXIT_STRATEGY = "BE+TP1+TP2"

# TP1_QTY_RATIO: The fraction of your position size exited at the first take-profit target (0.5 = 50%).
# Expect half of your position to close upon hitting the TP1 target price.
TP1_QTY_RATIO = 0.5

# TP1_BUFFER_PCT: The relative price distance spacing used to locate the TP1 profit target.
# Expect TP1 to be placed at this fraction of the distance between your entry and final TP.
TP1_BUFFER_PCT = 0.5

# CONTRARIAN_GLOBAL: Toggles inverting the final trade signal direction globally (Buy becomes Sell).
# Expect the execution engine to take shorts on bullish triggers and longs on bearish triggers when enabled.
CONTRARIAN_GLOBAL = False

# CONTRARIAN_FILTER: Toggles inverting the logic inside strategy entry filters.
# Expect entry filters to check bearish bounds to validate a buy order when enabled.
CONTRARIAN_FILTER = False

# USE_DRT_VELOCITY: Toggles checking DRT trend acceleration before taking trades.
# When enabled, expect trades to be blocked unless fast-DRT is accelerating in your trade direction.
USE_DRT_VELOCITY = False

# USE_ADAPTIVE_RSI: Enables adapting RSI overbought/oversold boundaries based on trend momentum.
# When enabled, expect RSI entry gates to tighten during weak trends and widen during strong momentum.
USE_ADAPTIVE_RSI = False

# USE_ATR_CAPPED_TP: Enables capping the maximum take-profit distance using 15m ATR multiples.
# When enabled, expect extremely wide take-profits to be restricted to protect against trend exhaustion.
USE_ATR_CAPPED_TP = False

# USE_VOL_ADJUSTED_RISK: Toggles reducing your trade risk fraction during high volatility regimes.
# When enabled, expect position sizing models to automatically half your risk when ATR exceeds thresholds.
USE_VOL_ADJUSTED_RISK = False

# RESTRICT_BTC_MOMENTUM: Enables gating trades based on Bitcoin's 15m momentum direction.
# When enabled, expect longs to be blocked if Bitcoin's 15m momentum is negative.
RESTRICT_BTC_MOMENTUM = False

# BTC_MOMENTUM_THRESHOLD: The minimum momentum rate required to pass the Bitcoin momentum gate.
# Expect trades to be blocked unless Bitcoin's rate of change exceeds this threshold.
BTC_MOMENTUM_THRESHOLD = 0.001

# BYPASS_GLOBAL_FILTERS: Toggles bypassing all Layer 1 safety checks (Correlations, Cooldowns, Regimes).
# When enabled, expect entries to bypass core checks and rely solely on strategy-internal triggers.
BYPASS_GLOBAL_FILTERS = False

# RESTRICT_BTC_CONFLUENCE: Enables gating trades based on Bitcoin's multi-timeframe trend alignment.
# When enabled, expect trades to be blocked unless aligned with Bitcoin's HTF direction.
RESTRICT_BTC_CONFLUENCE = False

# RESTRICT_ASSET_CONFLUENCE: Enables gating trades based on the asset's own 15m trend alignment.
# When enabled, expect longs to be blocked if the asset's 15m trend is bearish.
RESTRICT_ASSET_CONFLUENCE = False

# BTC_CONF_15M_MIN: The minimum 15m trend rate required to pass the Bitcoin confluence gate.
# Expect longs to be blocked unless Bitcoin's 15m trend rate exceeds this positive value.
BTC_CONF_15M_MIN = 0.0002

# BTC_CONF_1H_MIN: The minimum 1H trend rate required to pass the Bitcoin confluence gate.
# Expect longs to be blocked unless Bitcoin's 1H trend rate exceeds this positive value.
BTC_CONF_1H_MIN = 0.0002

# TREND_15M_MIN: The minimum trend rate required to count an asset's 15m trend as active.
# Expect trend scoring models to ignore weak movement below this threshold.
TREND_15M_MIN = 0.0001

# RESTRICT_DRT: Enables gating trades based on DRT trend strength floors.
# When enabled, expect trades to be blocked unless DRT confirms a strong active trend.
RESTRICT_DRT = False

# RESTRICT_CONFIDENCE: Enables gating trades based on minimum model prediction confidence.
# When enabled, expect signals to be discarded unless the confidence exceeds your minimum.
RESTRICT_CONFIDENCE = False

# RESTRICT_DIRECTIONAL_SANITY: Enables checking that model scoring matches the DRT trend direction.
# When enabled, expect longs to be blocked if DRT indicates a bearish premium.
RESTRICT_DIRECTIONAL_SANITY = False

# RESTRICT_RSI: Enables gating trades based on standard RSI overbought/oversold boundaries.
# When enabled, expect trades to be blocked unless RSI indicates an overextended extreme.
RESTRICT_RSI = False

# RESTRICT_RSI_SHORT_CEILING: Toggles checking the ADX trend strength when shorting at extreme RSI.
# When enabled, expect shorts to be blocked if RSI is extremely high and trend momentum is strong.
RESTRICT_RSI_SHORT_CEILING = False

# RESTRICT_MACD: Enables gating trades based on the MACD histogram direction.
# When enabled, expect longs to be blocked if the MACD histogram is negative.
RESTRICT_MACD = False

# RESTRICT_15M_TREND: Enables gating trades based on the 15m trend direction.
# When enabled, expect longs to be blocked if the 15m trend is negative.
RESTRICT_15M_TREND = False

# RESTRICT_SUPERTREND: Enables gating trades based on the Supertrend direction.
# When enabled, expect longs to be blocked if Supertrend is bearish.
RESTRICT_SUPERTREND = False

# RESTRICT_ATR: Enables gating trades based on a minimum absolute ATR volatility floor.
# When enabled, expect trades to be blocked on stagnant assets with zero volatility.
RESTRICT_ATR = False

# RESTRICT_VOL_PCT: Enables gating trades based on a minimum relative order book volume.
# When enabled, expect trades to be blocked if liquidity is too low for sizing.
RESTRICT_VOL_PCT = False

# RESTRICT_SPREAD: Enables gating trades based on a maximum allowed order book spread.
# When enabled, expect trades to be blocked if the bid-ask spread is wider than your limit.
RESTRICT_SPREAD = False

# RESTRICT_LIQUIDITY: Enables gating trades based on active bids/asks volume in the order book.
# When enabled, expect trades to be blocked if there are no active limits on either side.
RESTRICT_LIQUIDITY = False

# RESTRICT_SLIPPAGE: Enables checking actual entry execution slippage against your maximum limit.
# When enabled, expect entry fills to be rejected if they slip too far from your target limit.
RESTRICT_SLIPPAGE = False

# RESTRICT_SCORE: Enables gating trades based on a minimum absolute model prediction score.
# When enabled, expect signals to be discarded unless the scoring exceeds your required threshold.
RESTRICT_SCORE = False

# MIN_CONFIDENCE: The minimum confidence required to pass the confidence gate (0.66 = 66%).
# Expect signals to be discarded if their calculated prediction confidence falls below this floor.
MIN_CONFIDENCE = 0.66

# RESTRICT_IMBALANCE: Enables gating trades based on minimum order book bid/ask volume imbalance.
# When enabled, expect trades to be blocked unless order book volume points strongly in your trade direction.
RESTRICT_IMBALANCE = False

# RESTRICT_HTF_BIAS: Enables gating trades based on Higher Timeframe trend bias alignment.
# When enabled, expect longs to be blocked if the HTF trend bias is bearish.
RESTRICT_HTF_BIAS = False

# RESTRICT_VOLUME_INFLUX: Enables gating trades based on active volume influx or spikes.
# When enabled, expect trades to be blocked unless there is active volume expansion.
RESTRICT_VOLUME_INFLUX = False

# RESTRICT_MIN_VAL: Enables checking that the total trade value exceeds the exchange minimum.
# When enabled, expect signals to be rejected if the calculated contract size is below exchange limits.
RESTRICT_MIN_VAL = True

# RESTRICT_STRUCTURE: Enables gating trades based on market structure break alignment (BOS/MSS).
# When enabled, expect trades to be blocked unless a clear structure break is identified.
RESTRICT_STRUCTURE = False


# --- Logging & UI ---
# LOG_REJECTIONS: Enables printing verbose warning logs on rejected/filtered setups.
# Expect detailed diagnostic logs in console when enabled, while debug logs capture them otherwise.
LOG_REJECTIONS = False

# LOG_SIGNALS: Toggles printing strategy entry signals to the console output.
# Expect clear entry logs in console when enabled, while debug logs record them otherwise.
LOG_SIGNALS = True

# SHOW_PERIODIC_SUMMARY: Enables logging periodic performance summaries in the console.
# Expect clear equity, ROI, and trades summaries in console at regular intervals when enabled.
SHOW_PERIODIC_SUMMARY = True

# SUMMARY_INTERVAL_SECONDS: The interval duration in seconds between periodic summaries (30 = 30s).
# Expect performance summaries to print in the console at this regular interval.
SUMMARY_INTERVAL_SECONDS = 30

# SHOW_HEARTBEAT: Toggles logging periodic session heartbeats in the console.
# Expect session duration, asset counts, and signals progress to print at regular intervals when enabled.
SHOW_HEARTBEAT = True

# HEARTBEAT_INTERVAL_SECONDS: The interval duration in seconds between periodic heartbeats (30 = 30s).
# Expect session heartbeats to print in the console at this regular interval.
HEARTBEAT_INTERVAL_SECONDS = 30


# --- Simulator & Technical Analysis Internal Settings ---
# TICK_SECONDS: Configures the duration in seconds of a single tick in the paper matching engine (0.2 = 200ms).
# Expect order book updates and trade matching to cycle at this tick frequency.
TICK_SECONDS = 0.2

# INDICATOR_PRICE_HISTORY: The maximum history length maintained for calculating technical indicators (500 = 500 bars).
# Expect indicators calculation to slice and use this maximum length of historical OHLCV data.
INDICATOR_PRICE_HISTORY = 500

# MAKER_FEE: The exchange fee rate applied to maker transactions (0.0002 = 0.02%).
# Expect this fee rate to be subtracted from your balance on successful limit fills.
MAKER_FEE = 0.0002

# TAKER_FEE: The exchange fee rate applied to taker transactions (0.0006 = 0.06%).
# Expect this fee rate to be subtracted from your balance on successful market fills.
TAKER_FEE = 0.0006

# EXPECTED_SLIPPAGE: The expected price execution slippage fraction used in net P&L math (0.001 = 0.1%).
# Expect this slippage rate to be subtracted from your P&L to model realistic executions.
EXPECTED_SLIPPAGE = 0.001

# MAX_ENTRY_SLIPPAGE: The maximum allowed price slippage fraction during entry order fills (0.001 = 0.1%).
# Expect orders to be rejected if the actual fill price slips further than this limit.
MAX_ENTRY_SLIPPAGE = 0.001

# MAX_SPREAD_PCT: The maximum allowed bid-ask spread fraction inside the order book (0.002 = 0.2%).
# Expect trades to be blocked if the spread is wider than this relative limit.
MAX_SPREAD_PCT = 0.002

# FEE_AWARE_SIZING: Toggles adjusting your trade size for expected transaction fees.
# When enabled, expect position sizing models to automatically reduce size to cover entry/exit fees.
FEE_AWARE_SIZING = True

# BTC_REALTIME_CONFLUENCE: Toggles checking Bitcoin confluence trend bias in real-time during ticks.
# When enabled, expect Bitcoin's current price slope to affect active trade positions instantly.
BTC_REALTIME_CONFLUENCE = False

# SESSION_MULTIPLIER: The risk multiplier applied to positions taken during highly liquid sessions (London/NY).
# Expect position sizing models to increase your risk fraction by this multiple during these hours.
SESSION_MULTIPLIER = 1.5

# --- Config Context Class for Dependency Injection [ARCH-003] ---
class ConfigContext:
    """
    Immutable Configuration Context designed to isolate running execution parameters
    across threads or concurrent backtest variants, preventing global variable pollution.
    """
    def __init__(self, **kwargs):
        # Automatically capture all module-level parameters as instance defaults
        g = globals()
        for k, v in g.items():
            if not k.startswith("__") and k != "os" and k != "datetime" and k != "pytz" and k != "load_dotenv" and k != "get_env_stripped":
                # Ensure we do not copy classes or types
                if not isinstance(v, type):
                    setattr(self, k, v)
        # Apply overrides
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get(self, key, default=None):
        return getattr(self, key, default)
