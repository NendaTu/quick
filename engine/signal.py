"""
1. Summary: Typed Signal and OrderRequest definitions for execution payload standardization.
2. Description: Declares frozen dataclasses representing trade signal states and exchange order requests to replace untyped dictionary popping and prevent parameter naming collisions.
3. Context: Used by strategy engines to return signal payloads and routed by SignalRouter to exchange endpoints.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str
    order_type: str
    qty: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    tp_price: Optional[float] = None
    tp1_price: Optional[float] = None
    tp1_qty: Optional[float] = None
    tp2_price: Optional[float] = None
    tp2_qty: Optional[float] = None
    tp3_price: Optional[float] = None
    tp3_qty: Optional[float] = None
    strategy_id: str = "unknown"
    confidence: float = 0.5
    features: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert OrderRequest to a flat dictionary for backward compatibility."""
        res = {
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "qty": self.qty,
            "price": self.price,
            "entry_price": self.price,
            "stop_price": self.stop_price,
            "exit_price": self.tp_price,
            "tp_price": self.tp_price,
            "tp1_price": self.tp1_price,
            "tp1_qty": self.tp1_qty,
            "tp2_price": self.tp2_price,
            "tp2_qty": self.tp2_qty,
            "tp3_price": self.tp3_price,
            "tp3_qty": self.tp3_qty,
            "strategy_id": self.strategy_id,
            "confidence": self.confidence,
        }
        res.update(self.features)
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrderRequest":
        """Construct an OrderRequest from a dictionary."""
        features = {k: v for k, v in data.items() if k not in [
            "symbol", "side", "order_type", "qty", "price", "entry_price", "stop_price",
            "exit_price", "tp_price", "tp1_price", "tp1_qty", "tp2_price", "tp2_qty",
            "tp3_price", "tp3_qty", "strategy_id", "confidence"
        ]}
        return cls(
            symbol=data.get("symbol", ""),
            side=data.get("side", ""),
            order_type=data.get("order_type", "limit"),
            qty=float(data.get("qty", 0.0)),
            price=data.get("price") or data.get("entry_price"),
            stop_price=data.get("stop_price"),
            tp_price=data.get("exit_price") or data.get("tp_price"),
            tp1_price=data.get("tp1_price"),
            tp1_qty=data.get("tp1_qty"),
            tp2_price=data.get("tp2_price"),
            tp2_qty=data.get("tp2_qty"),
            tp3_price=data.get("tp3_price"),
            tp3_qty=data.get("tp3_qty"),
            strategy_id=data.get("strategy_id", "unknown"),
            confidence=float(data.get("confidence", 0.5)),
            features=features
        )
