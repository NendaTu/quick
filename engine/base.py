"""
1. Summary: Abstract Base Classes defining execution standards for exchange drivers and trading strategies.
2. Description: Establishes strict contracts for query methods (tickers, positions, orders) and transaction execution methods (orders, scaling). Establishes contracts for strategy modules to ingest market data and manage active trades.
3. Context: Inherited by BaseExchange drivers in engine/exchanges/ and BaseStrategy classes in strategies/.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Set

class BaseExchange(ABC):
    def __init__(self, config_context=None):
        self.config = config_context
        self.last_price: Dict[str, float] = {}
        self.ohlcv: Dict[str, Dict[str, List[dict]]] = {}
        self.books: Dict[str, Any] = {}
        self.db: Optional[Any] = None
        self.ready_assets: Set[str] = set()
        self.used_margin: float = 0.0
        self.symbol_map: Dict[str, str] = {}
        self.rev_symbol_map: Dict[str, str] = {}
        self.asset_correlations: Dict[str, Dict[str, float]] = {}

    @abstractmethod
    async def get_tickers(self) -> List[Dict]:
        pass

    @abstractmethod
    async def get_symbols(self) -> List[Dict]:
        pass

    @abstractmethod
    async def get_candles(self, symbol: str, timeframe: str, limit: int = 100) -> List[List]:
        pass

    @abstractmethod
    async def place_order(self, symbol: str, side: str, order_type: str, qty: float, price: Optional[float] = None, **kwargs) -> Dict:
        pass

    @abstractmethod
    async def scale_position(self, symbol: str, side: str, qty: float, **kwargs) -> Dict:
        pass

    @abstractmethod
    async def get_trading_equity(self) -> float:
        pass

    @abstractmethod
    async def get_positions(self) -> List[Dict]:
        pass

    @abstractmethod
    async def get_open_orders(self) -> List[Dict]:
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        pass

    @abstractmethod
    async def get_order_status(self, symbol: str, order_id: str) -> Dict:
        pass

    # Optional / Extended Capabilities with default no-op/fallback implementations (R1-3)
    def is_ready(self, symbol: str = None) -> bool:
        """Checks if the exchange is ready for data feeds."""
        return True

    async def get_open_tpsl_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Returns open TP/SL orders from the exchange."""
        return []

    async def get_history_positions(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Returns closed positions history from the exchange."""
        return []

    async def get_fills(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Returns trade fills history from the exchange."""
        return []

    async def recalculate_correlations(self) -> None:
        """Optional capability to recalculate asset price correlations."""
        pass

    async def close(self) -> None:
        """Unified async teardown interface (R2-2)."""
        pass


class BaseStrategy(ABC):
    def __init__(self, simulator=None, model=None, config_overrides: Optional[Dict] = None):
        self.simulator = simulator
        self.model = model
        self.config_overrides = config_overrides or {}
        self.name: str = "base_strategy"
        self.strategy_id: str = "base_strategy"
        self.params: Dict[str, Any] = {}

    @abstractmethod
    def get_entry_signal(self, market_data: Dict) -> Optional[Dict]:
        """
        Returns a signal dict if entry criteria are met:
        {
            "side": "buy" | "sell",
            "entry_price": float,
            "stop_price": float,
            "exit_price": float,
            "qty": float,
            ...
        }
        """
        pass

    @abstractmethod
    def manage_position(self, position: Dict, market_data: Dict) -> Optional[Dict]:
        """
        Called every tick to manage an open position.
        Can return an update dict (e.g., new SL/TP) or an exit signal.
        """
        pass

    def is_ready(self, symbol: str) -> bool:
        """Genuinely-required warmup completeness check (R1-3)."""
        return True

    def get_readiness_eta(self, symbol: str) -> str:
        """Returns human-readable readiness details or warmup countdown ETA."""
        return f"{symbol}: strategy ready."
