import math, random
from typing import List, Tuple

class SimulatedOrderBook:
    """Random‑walk order book used by the Simulator."""
    def __init__(self, symbol: str, initial_price: float, spread_pct: float = 0.0006):
        self.symbol = symbol
        self.mid_price = initial_price
        self.spread_pct = spread_pct
        self.bids: List[Tuple[float, float]] = []
        self.asks: List[Tuple[float, float]] = []
        self._regenerate()

    def _regenerate(self):
        half = self.spread_pct / 2
        self.bids = [
            (self.mid_price * (1 - half - i * 0.0001), random.uniform(500, 2000))
            for i in range(3)
        ]
        self.asks = [
            (self.mid_price * (1 + half + i * 0.0001), random.uniform(500, 2000))
            for i in range(3)
        ]

    def random_step(self, factor: float = None):
        """Advance price by a geometric random factor."""
        if factor is None:
            sigma = 0.0002
            factor = math.exp(random.gauss(0, sigma))
        self.mid_price *= factor
        self.spread_pct = max(0.0002, self.spread_pct + random.gauss(0, 0.00001))
        self._regenerate()

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