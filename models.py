import math
import logging
from config import *
from indicators import compute_drt, compute_rsi, compute_macd, compute_ema, compute_supertrend

log = logging.getLogger("scalper.models")

class LearningModel:
    def __init__(self, simulator):
        self.simulator = simulator

    def train_on_tick(self, symbol, prev_features, actual_up):
        pass

    def add_tick(self, symbol, prev_features, direction_up):
        pass

    def predict(self, symbol, book, equity):
        features = self.simulator.get_features(symbol)
        if not features:
            return None

        imb = features["imbalance"]
        if abs(imb) < MIN_IMBALANCE:
            return None

        # Directional trend strength (DRT)
        drt = features["drt"]

        # Confluence: BTC and asset alignment
        btc_1h = features.get("btc_1H", 0)
        asset_1h = features.get("asset_1H", 0)

        # Scoring
        score = 0
        if imb > 0.3:
            score += 2
        elif imb > 0.15:
            score += 1
        elif imb < -0.3:
            score -= 2
        elif imb < -0.15:
            score -= 1

        rsi = features["rsi"]
        if imb > 0 and rsi < 30:
            score += 1
        elif imb < 0 and rsi > 70:
            score -= 1

        macd_hist = features["macd_hist"]
        if macd_hist > 0 and imb > 0:
            score += 1
        elif macd_hist < 0 and imb < 0:
            score -= 1

        ema_short = features["ema_short"]
        ema_long = features["ema_long"]
        if ema_short > ema_long and imb > 0:
            score += 1
        elif ema_short < ema_long and imb < 0:
            score -= 1

        asset_15m = features.get("asset_15m", 0)
        if asset_15m > 0.001 and imb > 0:
            score += 1
        elif asset_15m < -0.001 and imb < 0:
            score -= 1

        # Check for trade signal (absolute score >= 2)
        if abs(score) < 2:
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
        # Risk per unit
        risk_per_unit = abs(entry - stop_price)
        if risk_per_unit == 0:
            return None

        qty = risk_amount / risk_per_unit
        qty = math.floor(qty * 1000) / 1000
        if qty <= 0:
            return None

        max_lev = LEVERAGE_LIMITS.get(symbol, 125)
        required_margin = (qty * entry) / max_lev
        if equity < required_margin:
            return None

        # BTC Confluence metrics for logging
        btc_conf = f"1D:{features.get('btc_1D', 0):.4f} 4H:{features.get('btc_4H', 0):.4f} 1H:{features.get('btc_1H', 0):.4f} 15m:{features.get('btc_15m', 0):.4f}"

        signal = {
            "side": direction,
            "entry_price": entry,
            "exit_price": exit_price,
            "stop_price": stop_price,
            "qty": qty,
            "confidence": min(1.0, (abs(score) + 2) / 10),
            "btc_confluence": btc_conf
        }

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
