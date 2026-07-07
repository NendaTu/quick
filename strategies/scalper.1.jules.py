"""
# Scalper Strategy v1.jules

## Overview
This strategy is the primary "institutional-grade" high-frequency compounding engine.
It is designed to identify high-probability entries in the Bitget USDT-M Futures market
by combining multiple technical analysis signals into a unified confidence score.

## Goals
- Target ROE: 20% per trade (configurable).
- Frequency: Target 10-20 trades per hour across 250 assets.
- Rationale: Small, consistent gains compounded rapidly.

## Modules Used
- **Imbalance/Flow**: Measures net aggressive volume delta. Essential for front-running micro-moves.
- **RSI/ADX**: Identifies momentum extremes and trend strength.
- **MACD**: Confirms directional momentum shifts.
- **Market Structure (BOS/MSS)**: Ensures entries align with institutional market flow.
- **POI/FVG**: Locates "Smart Money" zones for high-probability reactions.

## Flow
1. **Feature Extraction**: Polled every tick via Simulator/Engine.
2. **Scoring**: Weighted sum of indicator contributions (Learned via LearningModel).
3. **Hard Gates**: Strict filters for HTF bias, BTC confluence, and volatility regimes.
4. **Execution**: Dynamic position sizing via Kelly/Volatility scaling.
5. **Management**: Active breakeven triggers and multi-stage TP exits.

## Limitations
- Performance may degrade in extremely low-volatility "sideways" markets.
- High-frequency nature makes it sensitive to exchange latency and slippage on low-liquidity assets.
"""

import logging
from typing import Dict, Optional, Any
from strategies.base_strategy import JBaseStrategy
from models import LearningModel
import config

log = logging.getLogger("strategies.scalper")

class ScalperStrategy(JBaseStrategy):
    def __init__(self, config_overrides: Optional[Dict] = None, simulator=None):
        super().__init__(
            name="scalper",
            version="1",
            author="jules",
            config_overrides=config_overrides
        )
        # We'll pass the simulator to the LearningModel
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
