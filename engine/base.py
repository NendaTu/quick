from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

class BaseExchange(ABC):
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

class BaseStrategy(ABC):
    def __init__(self, config_overrides: Optional[Dict] = None):
        self.config_overrides = config_overrides or {}

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
