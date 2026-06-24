import math, random
from typing import List, Tuple

class SimulatedOrderBook:
    """Order book placeholder used by the Simulator, updated via WebSocket."""
    def __init__(self, symbol: str, initial_price: float, spread_pct: float = 0.0006):
        self.symbol = symbol
        self.mid_price = initial_price
        self.spread_pct = spread_pct
        self.bids: List[Tuple[float, float]] = []
        self.asks: List[Tuple[float, float]] = []
        self._regenerate()

    def _regenerate(self):
        """Initial dummy generation until real data arrives."""
        half = self.spread_pct / 2
        self.bids = [
            (self.mid_price * (1 - half - i * 0.0001), random.uniform(500, 2000))
            for i in range(3)
        ]
        self.asks = [
            (self.mid_price * (1 + half + i * 0.0001), random.uniform(500, 2000))
            for i in range(3)
        ]

    @property
    def best_bid(self): return self.bids[0][0] if self.bids else 0.0
    @property
    def best_ask(self): return self.asks[0][0] if self.asks else 0.0

    def top_bid_ask_qty(self):
        return sum(s for _, s in self.bids[:3]), sum(s for _, s in self.asks[:3])


class OrderBook:
    """Lightweight mirror used by the Engine for quick reads."""
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: List[Tuple[float, float]] = []
        self.asks: List[Tuple[float, float]] = []
        self.timestamp = 0.0

    @property
    def best_bid(self): return self.bids[0][0] if self.bids else 0.0
    @property
    def best_ask(self): return self.asks[0][0] if self.asks else 0.0

    def top_bid_ask_qty(self):
        bid_vol = sum(s for _, s in self.bids[:3])
        ask_vol = sum(s for _, s in self.asks[:3])
        return bid_vol, ask_vol
