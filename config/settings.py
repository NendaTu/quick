"""
1. Summary: Typed, validated settings model for application parameters.
2. Description: Declares pydantic models representing distinct configuration domains (Risk, Execution, Scoring, Logging, Simulator, Environment). Employs pydantic-settings to automatically pull parameters from environment variables with strong data validation.
3. Context: Used by config/__init__.py to boot and populate the application configuration system.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, BaseModel
from typing import List, Dict
from datetime import datetime, timezone

# R1-2 / Clarification 9.4: Non-environment settings groups remain plain BaseModel classes.
# This keeps deployment-level configuration (loaded from .env) strictly separated from
# runtime execution and strategy-tuning parameters (modified primarily via CLI overrides).

class AccountRiskSettings(BaseModel):
    USE_VIRTUAL_BALANCE: bool = False
    INITIAL_EQUITY: float = Field(40.0, ge=0.0)
    REINVESTMENT_PERCENTAGE: float = Field(1.0, ge=0.0, le=1.0)
    RISK_PER_TRADE: float = Field(0.01, ge=0.0, le=1.0)
    MAX_CONCURRENT_POSITIONS: int = Field(15, gt=0)
    MAX_AGGREGATE_MARGIN_PCT: float = Field(0.10, ge=0.0, le=1.0)
    DRAWDOWN_LIMIT: float = Field(0.25, ge=0.0, le=1.0)
    TOTAL_ROI_LIMIT: float = Field(1000.0, gt=0.0)
    MAX_TRADES_LIMIT: int = Field(5000, gt=0)
    MAX_DURATION: int = Field(86400, gt=0)

class AssetSettings(BaseModel):
    ASSETS_COUNT: int = Field(250, gt=0)
    ASSET_REDISCOVERY_HOURS: float = Field(6.0, gt=0.0)
    ASSET_OMITTED: List[str] = ["BTCUSDT"]
    BTC_SYMBOL: str = "BTCUSDT"

class ExecutionSettings(BaseModel):
    ENTRY_ORDER_TYPE: str = "limit"
    TP_ORDER_TYPE: str = "limit"  # Configures take-profit execution type in simulation. On live/demo, TP is executed at market (taker) for guaranteed filling.
    SL_ORDER_TYPE: str = "limit"  # Configures stop-loss execution type in simulation. On live/demo, SL is hardcoded to market (taker) for risk-management and guaranteed exit.
    SL_DISASTER_BUFFER: float = Field(0.001, ge=0.0, le=0.1)
    SL_MOVE: float = Field(0.004, ge=0.0, le=0.1)
    TP_MOVE: float = Field(0.008, ge=0.0, le=0.1)
    TARGET_NET_ROE: float = Field(0.20, ge=0.0, le=10.0)
    LIMIT_CHASE_TIMEOUT: float = Field(10.0, gt=0.0)

class StrategySettings(BaseModel):
    USE_ONLINE_LEARNING: bool = False
    REENTRY_COOLDOWN: float = Field(60.0, ge=0.0)
    MIN_SCALING_DISTANCE_PCT: float = Field(0.005, ge=0.0, le=1.0)
    MAX_ATR_EXPANSION_MULTIPLIER: float = Field(20.0, gt=0.0)
    MIN_NET_TP_PROFIT_PCT: float = Field(0.001, ge=0.0, le=1.0)
    USE_TP_RELAXATION: bool = False
    USE_TTL: bool = False
    TTL_CANDLE_MULTIPLIER: int = Field(15, gt=0)
    USE_BREAKEVEN_TRIGGER: bool = False
    BREAKEVEN_ROI_THRESHOLD: float = Field(0.20, ge=0.0)
    BREAKEVEN_PROFIT_BUFFER: float = Field(0.05, ge=0.0)
    EXIT_STRATEGY: str = "BE+TP1+TP2"
    TP1_QTY_RATIO: float = Field(0.5, ge=0.0, le=1.0)
    TP1_BUFFER_PCT: float = Field(0.5, ge=0.0, le=1.0)
    CONTRARIAN_GLOBAL: bool = False
    CONTRARIAN_FILTER: bool = False
    USE_DRT_VELOCITY: bool = False
    USE_ADAPTIVE_RSI: bool = False
    USE_ATR_CAPPED_TP: bool = False
    USE_VOL_ADJUSTED_RISK: bool = False
    BTC_MOMENTUM_THRESHOLD: float = Field(0.001, ge=0.0)
    BTC_CONF_15M_MIN: float = Field(0.0002, ge=0.0)
    BTC_CONF_1H_MIN: float = Field(0.0002, ge=0.0)
    TREND_15M_MIN: float = Field(0.0001, ge=0.0)
    MIN_CONFIDENCE: float = Field(0.66, ge=0.0, le=1.0)
    RESTRICT_MIN_VAL: bool = True
    RESTRICT_SLIPPAGE: bool = False
    RESTRICT_LIQUIDITY: bool = False

class ScoringWeightsSettings(BaseModel):
    ENTRY_SCORE_THRESHOLD: float = Field(15.0, ge=0.0, le=100.0)
    BY_DEFAULT_REPORT_ONLY: bool = False
    WEIGHT_RSI: float = Field(0.2, ge=0.0, le=10.0)
    WEIGHT_RSI_CEILING: float = Field(1.2, ge=0.0, le=10.0)
    WEIGHT_IMBALANCE: float = Field(1.5, ge=0.0, le=10.0)
    WEIGHT_MACD: float = Field(2.5, ge=0.0, le=10.0)
    WEIGHT_TREND_15M: float = Field(3.0, ge=0.0, le=10.0)
    # P2-3: WEIGHT_ASSET_CONF is removed per decisions to prevent double-counting.
    WEIGHT_SUPERTREND: float = Field(1.0, ge=0.0, le=10.0)
    WEIGHT_DRT: float = Field(2.0, ge=0.0, le=10.0)
    WEIGHT_SANITY: float = Field(3.5, ge=0.0, le=10.0)
    WEIGHT_BTC_MOM: float = Field(1.5, ge=0.0, le=10.0)
    WEIGHT_BTC_CONF: float = Field(1.5, ge=0.0, le=10.0)
    WEIGHT_HTF_BIAS: float = Field(3.5, ge=0.0, le=10.0)
    WEIGHT_STRUCTURE: float = Field(0.5, ge=0.0, le=10.0)
    WEIGHT_VOL_INFLUX: float = Field(1.0, ge=0.0, le=10.0)
    WEIGHT_ATR: float = Field(1.0, ge=0.0, le=10.0)
    WEIGHT_SPREAD: float = Field(1.0, ge=0.0, le=10.0)
    WEIGHT_VOL_PCT: float = Field(1.0, ge=0.0, le=10.0)
    WEIGHT_CONFIDENCE: float = Field(1.0, ge=0.0, le=10.0)

class LoggingSettings(BaseModel):
    LOG_REJECTIONS: bool = False
    LOG_SIGNALS: bool = False
    SHOW_PERIODIC_SUMMARY: bool = True
    SUMMARY_INTERVAL_SECONDS: int = Field(30, gt=0)
    SHOW_HEARTBEAT: bool = True
    HEARTBEAT_INTERVAL_SECONDS: int = Field(30, gt=0)

class SimulatorSettings(BaseModel):
    TICK_SECONDS: float = Field(0.2, gt=0.0)
    INDICATOR_PRICE_HISTORY: int = Field(500, gt=0)
    MAKER_FEE: float = Field(0.0002, ge=0.0, le=0.1)
    TAKER_FEE: float = Field(0.0006, ge=0.0, le=0.1)
    EXPECTED_SLIPPAGE: float = Field(0.001, ge=0.0, le=0.1)
    MAX_ENTRY_SLIPPAGE: float = Field(0.001, ge=0.0, le=0.1)
    MAX_SPREAD_PCT: float = Field(0.002, ge=0.0, le=0.1)
    FEE_AWARE_SIZING: bool = True
    BTC_REALTIME_CONFLUENCE: bool = False
    SESSION_MULTIPLIER: float = Field(1.5, ge=0.0)

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

    def validate_credentials(self) -> None:
        """
        Validates that required credentials are present for the selected MODE (live or demo).
        Required Environment Variables:
        - For 'live' mode: BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE
        - For 'demo' mode: BITGET_API_KEY_DEMO, BITGET_SECRET_KEY_DEMO, BITGET_PASSPHRASE_DEMO
        """
        mode = self.MODE.lower()
        if mode == "live":
            required = {
                "BITGET_API_KEY": self.BITGET_API_KEY,
                "BITGET_SECRET_KEY": self.BITGET_SECRET_KEY,
                "BITGET_PASSPHRASE": self.BITGET_PASSPHRASE,
            }
        elif mode == "demo":
            required = {
                "BITGET_API_KEY_DEMO": self.BITGET_API_KEY_DEMO,
                "BITGET_SECRET_KEY_DEMO": self.BITGET_SECRET_KEY_DEMO,
                "BITGET_PASSPHRASE_DEMO": self.BITGET_PASSPHRASE_DEMO,
            }
        else:
            return

        missing = [k for k, v in required.items() if not v or v.strip() == ""]
        if missing:
            raise ValueError(f"Missing required credentials for '{mode}' mode: {', '.join(missing)}")

class Settings(BaseModel):
    env: EnvironmentSettings = Field(default_factory=EnvironmentSettings)
    risk: AccountRiskSettings = Field(default_factory=AccountRiskSettings)
    assets: AssetSettings = Field(default_factory=AssetSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    strategy: StrategySettings = Field(default_factory=StrategySettings)
    scoring: ScoringWeightsSettings = Field(default_factory=ScoringWeightsSettings)
    logging_ui: LoggingSettings = Field(default_factory=LoggingSettings)
    simulator: SimulatorSettings = Field(default_factory=SimulatorSettings)
