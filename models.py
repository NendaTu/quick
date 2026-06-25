import math
import logging
from config import *
from indicators import compute_drt, compute_rsi, compute_macd, compute_ema, compute_supertrend

log = logging.getLogger("scalper.models")

class LearningModel:
    def __init__(self, simulator):
        self.simulator = simulator
        self.weights = {
            "imbalance": 1.0,
            "rsi": 1.0,
            "macd": 1.0,
            "ema": 1.0,
            "trend": 1.0
        }
        self.lr = 0.0 # Disabled as per user request "Not yet"

    def train_on_tick(self, symbol, prev_features, actual_up):
        # Very basic online learning: increment weight if indicator was correct, decrement if wrong

        # 1. Imbalance
        imb = prev_features.get("imbalance", 0)
        if imb != 0:
            pred_up = imb > 0
            self.weights["imbalance"] += self.lr if pred_up == actual_up else -self.lr

        # 2. RSI
        rsi = prev_features.get("rsi", 50)
        if rsi < 45 or rsi > 55:
            pred_up = rsi < 45
            self.weights["rsi"] += self.lr if pred_up == actual_up else -self.lr

        # 3. MACD
        macd_hist = prev_features.get("macd_hist", 0)
        if macd_hist != 0:
            pred_up = macd_hist > 0
            self.weights["macd"] += self.lr if pred_up == actual_up else -self.lr

        # 4. EMA
        ema_short = prev_features.get("ema_short", 0)
        ema_long = prev_features.get("ema_long", 0)
        if ema_short != ema_long:
            pred_up = ema_short > ema_long
            self.weights["ema"] += self.lr if pred_up == actual_up else -self.lr

        # 5. Trend
        asset_15m = prev_features.get("asset_15m", 0)
        if abs(asset_15m) > 0.0001:
            pred_up = asset_15m > 0
            self.weights["trend"] += self.lr if pred_up == actual_up else -self.lr

        # Keep weights in a reasonable range
        for k in self.weights:
            self.weights[k] = max(0.1, min(5.0, self.weights[k]))

    def predict(self, symbol, book, equity, features=None):
        if features is None:
            features = self.simulator.get_features(symbol)

        if not features:
            return None

        # 1. Trend Strength Filter (Symmetric)
        drt = features.get("drt", 0.5)
        trend_offset = abs(drt - 0.5)
        if RESTRICT_DRT and trend_offset < TREND_STRENGTH_MIN:
            log.debug(f"REJECT {symbol}: Trend strength {trend_offset:.4f} < {TREND_STRENGTH_MIN}")
            return None

        imb = features.get("imbalance", 0)
        # 2. Imbalance filter
        if RESTRICT_IMBALANCE and abs(imb) < MIN_IMBALANCE:
            log.debug(f"REJECT {symbol}: Imbalance {imb:.4f} < {MIN_IMBALANCE}")
            return None

        # --- SCORING WITH LEARNED WEIGHTS ---
        score = 0

        # Imbalance contribution
        imb_score = 0
        if imb > 0.10: imb_score = 2
        elif imb > MIN_IMBALANCE: imb_score = 1
        elif imb < -0.10: imb_score = -2
        elif imb < -MIN_IMBALANCE: imb_score = -1

        if RESTRICT_IMBALANCE or not RESTRICT_SCORE:
            score += imb_score * self.weights["imbalance"]

        # RSI contribution
        rsi = features.get("rsi", 50)
        rsi_score = 0
        if rsi < RSI_LONG: rsi_score = 1
        elif rsi > RSI_SHORT: rsi_score = -1

        if RESTRICT_RSI or not RESTRICT_SCORE:
            score += rsi_score * self.weights["rsi"]

        # MACD contribution
        macd_hist = features.get("macd_hist", 0)
        macd_score = 0
        if macd_hist > 0: macd_score = 1
        elif macd_hist < 0: macd_score = -1

        if RESTRICT_MACD or not RESTRICT_SCORE:
            score += macd_score * self.weights["macd"]

        # Trend/Confluence contribution
        asset_15m = features.get("asset_15m", 0)
        trend_score = 0
        if asset_15m > TREND_15M_MIN: trend_score = 1
        elif asset_15m < -TREND_15M_MIN: trend_score = -1

        if RESTRICT_15M_TREND or not RESTRICT_SCORE:
            score += trend_score * self.weights["trend"]

        # Check for trade signal
        if RESTRICT_SCORE and abs(score) < 1:
            log.debug(f"REJECT {symbol}: Score {score:.1f} < 1")
            return None

        # Confidence calculation
        confidence = min(1.0, (abs(score) + 1) / 10)
        if RESTRICT_CONFIDENCE and confidence < MIN_CONFIDENCE:
            log.debug(f"REJECT {symbol}: Confidence {confidence:.2f} < {MIN_CONFIDENCE}")
            return None

        # Direction check: ensure scoring matches the DRT trend
        if RESTRICT_DIRECTIONAL_SANITY:
            if score > 0 and drt < 0.5:
                log.debug(f"REJECT {symbol}: Long score with bearish DRT {drt:.4f}")
                return None
            if score < 0 and drt > 0.5:
                log.debug(f"REJECT {symbol}: Short score with bullish DRT {drt:.4f}")
                return None

        # If everything is False, we still need a direction
        # Priority: Score Direction -> Imbalance -> DRT
        if score > 0: direction = "buy"
        elif score < 0: direction = "sell"
        elif imb > 0: direction = "buy"
        elif imb < 0: direction = "sell"
        else: direction = "buy" if drt >= 0.5 else "sell"

        # RSI Restrictions
        if RESTRICT_RSI:
            if direction == "buy":
                if rsi > RSI_LONG:
                    log.debug(f"REJECT {symbol}: RSI {rsi:.1f} > {RSI_LONG}")
                    return None
                if rsi < RSI_BUY_FLOOR:
                    log.debug(f"REJECT {symbol}: RSI {rsi:.1f} < {RSI_BUY_FLOOR} (Floor)")
                    return None
            if direction == "sell":
                if rsi < RSI_SHORT:
                    log.debug(f"REJECT {symbol}: RSI {rsi:.1f} < {RSI_SHORT}")
                    return None
                if rsi > RSI_SHORT_CEILING:
                    log.debug(f"REJECT {symbol}: RSI {rsi:.1f} > {RSI_SHORT_CEILING} (Ceiling)")
                    return None

        # BTC Confluence Restrictions
        if RESTRICT_BTC_CONFLUENCE:
            btc_15m = features.get("btc_15m", 0)
            btc_1h = features.get("btc_1h", 0)
            if direction == "buy":
                if btc_15m < BTC_CONF_15M_MIN or btc_1h < BTC_CONF_1H_MIN:
                    log.debug(f"REJECT {symbol}: BTC 15m/1h [{btc_15m:.4f}/{btc_1h:.4f}] < {BTC_CONF_15M_MIN}")
                    return None
            else: # sell
                if btc_15m > -BTC_CONF_15M_MIN or btc_1h > -BTC_CONF_1H_MIN:
                    log.debug(f"REJECT {symbol}: BTC 15m/1h [{btc_15m:.4f}/{btc_1h:.4f}] > {-BTC_CONF_15M_MIN}")
                    return None

        entry = book.best_ask if direction == "buy" else book.best_bid
        max_lev = LEVERAGE_LIMITS.get(symbol, 125)

        # Dynamic TP/SL calculation
        if USE_DYNAMIC_TARGETS:
            # TP = Net ROE target + fees (entry + exit)
            entry_fee_rate = MAKER_FEE if ENTRY_ORDER_TYPE == "limit" else TAKER_FEE
            exit_fee_rate = MAKER_FEE if TP_ORDER_TYPE == "limit" else TAKER_FEE

            # Use max_lev to determine required price move for TARGET_NET_ROE
            tp_move = (TARGET_NET_ROE / max_lev) + (entry_fee_rate + exit_fee_rate)

            # Safety: ensure tp_move is at least a minimum threshold or the config baseline
            tp_move = max(tp_move, TP_MOVE)
        else:
            tp_move = TP_MOVE

        if USE_ATR_SL and features.get("atr"):
            sl_move = (features["atr"] * ATR_SL_MULT) / entry
        else:
            sl_move = SL_MOVE

        if direction == "buy":
            exit_price = entry * (1 + tp_move)
            stop_price = entry * (1 - sl_move)
        else:
            exit_price = entry * (1 - tp_move)
            stop_price = entry * (1 + sl_move)

        risk_amount = equity * RISK_PER_TRADE
        risk_per_unit = abs(entry - stop_price)
        if risk_per_unit == 0:
            return None

        qty = risk_amount / risk_per_unit

        # Respect contract precision
        spec = self.simulator.contract_specs.get(symbol, {})
        vol_place = int(spec.get('volumePlace', 3))
        price_place = int(spec.get('pricePlace', 2))

        qty = math.floor(qty * (10 ** vol_place)) / (10 ** vol_place)
        if qty <= 0:
            return None

        # Round prices
        entry = round(entry, price_place)
        exit_price = round(exit_price, price_place)
        stop_price = round(stop_price, price_place)

        max_lev = LEVERAGE_LIMITS.get(symbol, 125)
        required_margin = (qty * entry) / max_lev
        if equity < required_margin:
            return None

        btc_conf = f"1D:{features.get('btc_1D', 0):.4f} 4H:{features.get('btc_4H', 0):.4f} 1H:{features.get('btc_1H', 0):.4f} 15m:{features.get('btc_15m', 0):.4f}"

        signal = {
            "side": direction,
            "entry_price": entry,
            "exit_price": exit_price,
            "stop_price": stop_price,
            "qty": qty,
            "confidence": confidence,
            "btc_confluence": btc_conf
        }

        # Tag Premium/Discount for analysis
        drt_fast = features.get("drt_fast", 0.5)
        drt_slow = features.get("drt_slow", 0.5)

        premium_fast = "PREM" if drt_fast > 0.5 else "DISC"
        premium_slow = "PREM" if drt_slow > 0.5 else "DISC"

        signal.update({
            "vol_pct": features.get("vol_pct", 0),
            "rsi": rsi,
            "atr": features.get("atr", 0),
            "macd": features.get("macd", 0),
            "drt": features.get("drt", 0.5),
            "drt_f": f"{drt_fast:.4f}({premium_fast})",
            "drt_s": f"{drt_slow:.4f}({premium_slow})"
        })
        return signal

class DummyModel:
    def predict(self, symbol, book, equity=None):
        return None
