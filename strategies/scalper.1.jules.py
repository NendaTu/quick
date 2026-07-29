"""
1. Summary: Jules high-frequency compounding scalper strategy.
2. Description: Harnesses moving average slopes, DRT momentum, and machine learning model predictions to execute tight scalps. Evaluates macro trends on higher timeframes and structures entry targets using ATR volatility.
3. Context: Relies on models.py and indicators in ta/. Loaded by main.py or backtest.py as a primary trading strategy.
"""
import logging
from typing import Dict, Optional, Any
from strategies.base_strategy import JBaseStrategy
from models import LearningModel
import config

class ScalperStrategy(JBaseStrategy):
    def __init__(self, config_overrides: Optional[Dict] = None, simulator=None, model=None):
        super().__init__(
            name="scalper",
            version="1",
            author="jules",
            simulator=simulator,
            model=model,
            config_overrides=config_overrides
        )
        # P0-2: Use the injected LearningModel to avoid the online-learning split-brain
        if model is not None:
            self.model = model
        else:
            self.model = LearningModel(simulator)

    def get_entry_signal(self, market_data: Dict) -> Optional[Dict]:
        """
        Uses the existing LearningModel.predict logic to generate an entry signal.
        market_data expects 'symbol', 'book', 'equity', and optionally 'features'.
        """
        symbol = market_data["symbol"]
        book = market_data["book"]
        equity = market_data["equity"]
        features = market_data.get("features")

        signal = self.model.predict(symbol, book, equity, features=features)

        if signal:
            # Enrich signal with strategy identification
            signal["symbol"] = symbol
            signal["strategy_id"] = self.strategy_id
            return signal

        return None

    def manage_position(self, position: Dict, market_data: Dict) -> Optional[Dict]:
        """
        Management is currently handled by Simulator/Engine's internal loop
        (Breakeven triggers, TTL, etc.).
        In this v1, we delegate to the existing core, but the interface is ready.
        """
        return None
