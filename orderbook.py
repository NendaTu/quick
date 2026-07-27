"""
1. Summary: Memory-efficient order book mirror and simulated order book generator.
2. Description: Defines OrderBook to maintain a real-time copy of bid/ask levels for spread/imbalance calculation. Defines SimulatedOrderBook to generate realistic dummy books until actual exchange data streams arrive.
3. Context: Used by engine/core.py and simulator.py to calculate spread and book metrics.
"""
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

    def update(self, bids: List[List], asks: List[List], ts: float = 0.0):
        """Updates the order book with new data."""
        if bids:
            self.bids = [(float(p), float(s)) for p, s in bids]
        if asks:
            self.asks = [(float(p), float(s)) for p, s in asks]
        if ts > 0:
            self.timestamp = ts
