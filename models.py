import math
from config import *
from indicators import compute_drt

class LearningModel:
    def __init__(self, simulator):
        self.simulator = simulator

    def train_on_tick(self, symbol, prev_features, actual_up):
        pass

    def add_tick(self, symbol, prev_features, direction_up):
        pass

    def predict(self, symbol, book, equity):
        features = self.simulator.get_features(symbol)
        imb = features["imbalance"]
        if abs(imb) < MIN_IMBALANCE:
            return None

        # Directional trend strength (DRT)
        drt = features["drt"]
        # Note: current DRT check is intentionally weak (see discussion); can be tightened in config

        # Confluence: BTC and asset alignment on 1H
        btc_1h = features.get("btc_1H", 0)
        asset_1h = features.get("asset_1H", 0)
        if abs(asset_1h) > 0.001 and btc_1h * asset_1h < 0:
            return None

        # RSI, MACD, EMA
        rsi = features["rsi"]
        macd_hist = features["macd_hist"]
        ema_short = features["ema_short"]
        ema_long = features["ema_long"]

        # Simple scoring
        score = 0
        if imb > 0.3:
            score += 2
        elif imb > 0.15:
            score += 1
        elif imb < -0.3:
            score -= 2
        elif imb < -0.15:
            score -= 1

        if imb > 0 and rsi < 30:
            score += 1
        elif imb < 0 and rsi > 70:
            score += 1

        if macd_hist > 0 and imb > 0:
            score += 1
        elif macd_hist < 0 and imb < 0:
            score += 1

        if ema_short > ema_long and imb > 0:
            score += 1
        elif ema_short < ema_long and imb < 0:
            score += 1

        asset_15m = features.get("asset_15m", 0)
        if asset_15m > 0.001 and imb > 0:
            score += 1
        elif asset_15m < -0.001 and imb < 0:
            score += 1

        if score < 2:
            return None

        direction = "buy" if score > 0 else "sell"

        entry = book.best_ask if direction == "buy" else book.best_bid
        tp_move = TP_MOVE
        sl_move = SL_MOVE
        if direction == "buy":
            exit_price = entry * (1 + tp_move)
            stop_price = entry * (1 - sl_move)
        else:
            exit_price = entry * (1 - tp_move)
            stop_price = entry * (1 + sl_move)

        risk_amount = equity * RISK_PER_TRADE
        qty = risk_amount / (entry * sl_move)
        qty = math.floor(qty * 1000) / 1000
        if qty <= 0:
            return None

        max_lev = LEVERAGE_LIMITS.get(symbol, 125)
        required_margin = (qty * entry) / max_lev
        if equity < required_margin:
            return None

        signal = {
            "side": direction,
            "entry_price": entry,
            "exit_price": exit_price,
            "stop_price": stop_price,
            "qty": qty,
            "confidence": min(1.0, (score + 2) / 10),
        }
        # Add indicator snapshot
        signal.update({
            "vol_pct": features.get("vol_pct", 0),
            "rsi": rsi,
            "atr": features.get("atr", 0),
            "macd": features.get("macd", 0),
            "ema_short": ema_short,
            "ema_long": ema_long,
            "supertrend": features.get("supertrend", 0),
            "drt": drt,
        })
        return signal

class DummyModel:
    def predict(self, symbol, book, equity=None):
        return None