"""
1. Summary: Typed, validated settings model for application parameters.
2. Description: Declares pydantic models representing distinct configuration domains (Risk, Execution, Scoring, Logging, Simulator, Environment). Employs pydantic-settings to automatically pull parameters from environment variables with strong data validation.
3. Context: Used by config/__init__.py to boot and populate the application configuration system.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, BaseModel
from typing import List, Dict
from datetime import datetime, timezone

class AccountRiskSettings(BaseModel):
    USE_VIRTUAL_BALANCE: bool = False
    INITIAL_EQUITY: float = 40.0
    REINVESTMENT_PERCENTAGE: float = 1.0
    RISK_PER_TRADE: float = 0.01
    MAX_CONCURRENT_POSITIONS: int = 15
    MAX_AGGREGATE_MARGIN_PCT: float = 0.10
    DRAWDOWN_LIMIT: float = 0.25
    TOTAL_ROI_LIMIT: float = 1000.0
    MAX_TRADES_LIMIT: int = 5000
    MAX_DURATION: int = 86400

class AssetSettings(BaseModel):
    ASSETS_COUNT: int = 250
    ASSET_REDISCOVERY_HOURS: float = 6.0
    ASSET_OMITTED: List[str] = ["BTCUSDT"]
    BTC_SYMBOL: str = "BTCUSDT"

class ExecutionSettings(BaseModel):
    ENTRY_ORDER_TYPE: str = "limit"
    TP_ORDER_TYPE: str = "limit"
    SL_ORDER_TYPE: str = "limit"
    SL_DISASTER_BUFFER: float = 0.001
    SL_MOVE: float = 0.004
    TP_MOVE: float = 0.008
    TARGET_NET_ROE: float = 0.20
    LIMIT_CHASE_TIMEOUT: float = 10.0

class StrategySettings(BaseModel):
    USE_ONLINE_LEARNING: bool = False
    REENTRY_COOLDOWN: float = 60.0
    MIN_SCALING_DISTANCE_PCT: float = 0.005
    MAX_ATR_EXPANSION_MULTIPLIER: float = 20.0
    MIN_NET_TP_PROFIT_PCT: float = 0.001
    USE_TP_RELAXATION: bool = False
    USE_TTL: bool = False
    TTL_CANDLE_MULTIPLIER: int = 15
    USE_BREAKEVEN_TRIGGER: bool = False
    BREAKEVEN_ROI_THRESHOLD: float = 0.20
    BREAKEVEN_PROFIT_BUFFER: float = 0.05
    EXIT_STRATEGY: str = "BE+TP1+TP2"
    TP1_QTY_RATIO: float = 0.5
    TP1_BUFFER_PCT: float = 0.5
    CONTRARIAN_GLOBAL: bool = False
    CONTRARIAN_FILTER: bool = False
    USE_DRT_VELOCITY: bool = False
    USE_ADAPTIVE_RSI: bool = False
    USE_ATR_CAPPED_TP: bool = False
    USE_VOL_ADJUSTED_RISK: bool = False
    BTC_MOMENTUM_THRESHOLD: float = 0.001
    BTC_CONF_15M_MIN: float = 0.0002
    BTC_CONF_1H_MIN: float = 0.0002
    TREND_15M_MIN: float = 0.0001
    MIN_CONFIDENCE: float = 0.66
    RESTRICT_MIN_VAL: bool = True
    RESTRICT_SLIPPAGE: bool = False
    RESTRICT_LIQUIDITY: bool = False

class ScoringWeightsSettings(BaseModel):
    ENTRY_SCORE_THRESHOLD: float = 15.0
    BY_DEFAULT_REPORT_ONLY: bool = False
    WEIGHT_RSI: float = 0.2
    WEIGHT_RSI_CEILING: float = 1.2
    WEIGHT_IMBALANCE: float = 1.5
    WEIGHT_MACD: float = 2.5
    WEIGHT_TREND_15M: float = 3.0
    # P2-3: WEIGHT_ASSET_CONF is removed per decisions to prevent double-counting.
    WEIGHT_SUPERTREND: float = 1.0
    WEIGHT_DRT: float = 2.0
    WEIGHT_SANITY: float = 3.5
    WEIGHT_BTC_MOM: float = 1.5
    WEIGHT_BTC_CONF: float = 1.5
    WEIGHT_HTF_BIAS: float = 3.5
    WEIGHT_STRUCTURE: float = 0.5
    WEIGHT_VOL_INFLUX: float = 1.0
    WEIGHT_ATR: float = 1.0
    WEIGHT_SPREAD: float = 1.0
    WEIGHT_VOL_PCT: float = 1.0
    WEIGHT_CONFIDENCE: float = 1.0

class LoggingSettings(BaseModel):
    LOG_REJECTIONS: bool = False
    LOG_SIGNALS: bool = False
    SHOW_PERIODIC_SUMMARY: bool = True
    SUMMARY_INTERVAL_SECONDS: int = 30
    SHOW_HEARTBEAT: bool = True
    HEARTBEAT_INTERVAL_SECONDS: int = 30

class SimulatorSettings(BaseModel):
    TICK_SECONDS: float = 0.2
    INDICATOR_PRICE_HISTORY: int = 500
    MAKER_FEE: float = 0.0002
    TAKER_FEE: float = 0.0006
    EXPECTED_SLIPPAGE: float = 0.001
    MAX_ENTRY_SLIPPAGE: float = 0.001
    MAX_SPREAD_PCT: float = 0.002
    FEE_AWARE_SIZING: bool = True
    BTC_REALTIME_CONFLUENCE: bool = False
    SESSION_MULTIPLIER: float = 1.5

class EnvironmentSettings(BaseSettings):
    MODE: str = "paper"
    BITGET_API_KEY: str = ""
    BITGET_SECRET_KEY: str = ""
    BITGET_PASSPHRASE: str = ""
    BITGET_API_KEY_DEMO: str = ""
    BITGET_SECRET_KEY_DEMO: str = ""
    BITGET_PASSPHRASE_DEMO: str = ""

    # Typed env loading from .env
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

class Settings(BaseModel):
    env: EnvironmentSettings = Field(default_factory=EnvironmentSettings)
    risk: AccountRiskSettings = Field(default_factory=AccountRiskSettings)
    assets: AssetSettings = Field(default_factory=AssetSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    strategy: StrategySettings = Field(default_factory=StrategySettings)
    scoring: ScoringWeightsSettings = Field(default_factory=ScoringWeightsSettings)
    logging_ui: LoggingSettings = Field(default_factory=LoggingSettings)
    simulator: SimulatorSettings = Field(default_factory=SimulatorSettings)
