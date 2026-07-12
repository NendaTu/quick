import math
import logging
import config
from tools.trading_utils import calculate_position_size, calculate_tp_for_roe, calculate_kelly_size
import ta.indicators.rsi as rsi_ind
import ta.indicators.atr as atr_ind
import ta.indicators.flow as flow_ind
import ta.patterns.drt as drt_pat
import ta.patterns.fvg as fvg_pat
from ta.indicators.macd import compute_macd
from ta.indicators.ema import compute_ema
from ta.indicators.supertrend import compute_supertrend
from ta.indicators.adx import compute_adx, STRONG_TREND_THRESHOLD

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
        self.lr = 0.01
        self._load_shared_weights()

    def _load_shared_weights(self):
        if hasattr(self.simulator, "db") and self.simulator.db:
            shared = self.simulator.db.get_weights()
            if shared:
                for k, v in shared.items():
                    if k in self.weights:
                        self.weights[k] = v

    def _save_shared_weights(self):
        if hasattr(self.simulator, "db") and self.simulator.db:
            for k, v in self.weights.items():
                self.simulator.db.save_weight(k, v)

    def train_on_trade(self, symbol, features, pnl):
        """
        [C-004] Real-time Reinforcement Learning: Adjust weights based on trade success.
        """
        cfg = self.simulator.config
        if not getattr(cfg, 'USE_ONLINE_LEARNING', False):
            return

        side = features.get("side", "buy")
        impact = 1.0 if pnl > 0 else -1.0

        def get_adjustment(indicator_score):
            if indicator_score == 0: return 0
            indicator_matches_side = (indicator_score > 0 and side == "buy") or (indicator_score < 0 and side == "sell")
            return self.lr * impact * (1.0 if indicator_matches_side else -1.0)

        self.weights["imbalance"] += get_adjustment(features.get("imb_score", 0))
        self.weights["rsi"] += get_adjustment(features.get("rsi_score", 0))
        self.weights["macd"] += get_adjustment(features.get("macd_score", 0))
        self.weights["trend"] += get_adjustment(features.get("trend_score", 0))

        for k in self.weights:
            self.weights[k] = max(0.1, min(5.0, self.weights[k]))

        self._save_shared_weights()

    def train_on_tick(self, symbol, prev_features, actual_up):
        cfg = self.simulator.config
        if not getattr(cfg, 'USE_ONLINE_LEARNING', False):
            return

        imb = prev_features.get("imbalance", 0)
        if imb != 0:
            pred_up = imb > 0
            self.weights["imbalance"] += self.lr if pred_up == actual_up else -self.lr

        rsi = prev_features.get("rsi", 50)
        if rsi < 45 or rsi > 55:
            pred_up = rsi < 45
            self.weights["rsi"] += self.lr if pred_up == actual_up else -self.lr

        macd_hist = prev_features.get("macd_hist", 0)
        if macd_hist != 0:
            pred_up = macd_hist > 0
            self.weights["macd"] += self.lr if pred_up == actual_up else -self.lr

        ema_short = prev_features.get("ema_short", 0)
        ema_long = prev_features.get("ema_long", 0)
        if ema_short != ema_long:
            pred_up = ema_short > ema_long
            self.weights["ema"] += self.lr if pred_up == actual_up else -self.lr

        asset_15m = prev_features.get("asset_15m", 0)
        if abs(asset_15m) > 0.0001:
            pred_up = asset_15m > 0
            self.weights["trend"] += self.lr if pred_up == actual_up else -self.lr

        for k in self.weights:
            self.weights[k] = max(0.1, min(5.0, self.weights[k]))

    def predict(self, symbol, book, equity, features=None):
        """
        Predicts direction and calculates risk-adjusted position size.
        """
        cfg = self.simulator.config

        if features is None:
            features = self.simulator.get_features(symbol)

        if not features:
            return None

        # 1. Trend Strength Filter (Symmetric)
        drt = features.get("drt", 0.5)
        trend_offset = abs(drt - 0.5)
        if getattr(cfg, 'RESTRICT_DRT', False) and trend_offset < drt_pat.STRENGTH_MIN:
            return None

        imb = features.get("imbalance", 0)
        # 2. Imbalance filter
        if getattr(cfg, 'RESTRICT_IMBALANCE', True) and abs(imb) < flow_ind.MIN_IMBALANCE:
            return None

        # 3. Liquidity/Volume filter
        vol_pct = features.get("vol_pct", 0)
        if getattr(cfg, 'RESTRICT_VOL_PCT', False) and vol_pct < flow_ind.VOL_PCT_MIN:
            return None

        # 4. Spread filter
        mid = features.get("mid", 0)
        book_bid, book_ask = book.best_bid, book.best_ask
        spread_pct = (book_ask - book_bid) / mid if mid > 0 else 0
        if getattr(cfg, 'RESTRICT_SPREAD', False) and spread_pct > getattr(cfg, 'MAX_SPREAD_PCT', 0.002):
            return None

        # 5. ATR filter
        atr = features.get("atr", 0)
        if getattr(cfg, 'RESTRICT_ATR', False) and atr < atr_ind.MIN_VOLATILITY:
            return None

        # --- SCORING WITH LEARNED WEIGHTS ---
        score = 0

        # Imbalance contribution
        imb_score = 0
        if imb > 0.10: imb_score = 2
        elif imb > flow_ind.MIN_IMBALANCE: imb_score = 1
        elif imb < -0.10: imb_score = -2
        elif imb < -flow_ind.MIN_IMBALANCE: imb_score = -1

        if getattr(cfg, 'RESTRICT_IMBALANCE', True) or not getattr(cfg, 'RESTRICT_SCORE', False):
            score += imb_score * self.weights["imbalance"]
            features["imb_score"] = imb_score

        # RSI contribution
        rsi = features.get("rsi", 50)
        rsi_score = 0
        if rsi < rsi_ind.LONG_THRESHOLD: rsi_score = 1
        elif rsi > rsi_ind.SHORT_THRESHOLD: rsi_score = -1

        if getattr(cfg, 'RESTRICT_RSI', False) or not getattr(cfg, 'RESTRICT_SCORE', False):
            score += rsi_score * self.weights["rsi"]
            features["rsi_score"] = rsi_score

        # MACD contribution
        macd_hist = features.get("macd_hist", 0)
        macd_score = 0
        if macd_hist > 0: macd_score = 1
        elif macd_hist < 0: macd_score = -1

        if getattr(cfg, 'RESTRICT_MACD', False) or not getattr(cfg, 'RESTRICT_SCORE', False):
            score += macd_score * self.weights["macd"]
            features["macd_score"] = macd_score

        # Trend/Confluence contribution
        asset_15m = features.get("asset_15m", 0)
        trend_score = 0
        trend_15m_min = getattr(cfg, 'TREND_15M_MIN', 0.0001)
        if asset_15m > trend_15m_min: trend_score = 1
        elif asset_15m < -trend_15m_min: trend_score = -1

        if getattr(cfg, 'RESTRICT_15M_TREND', False) or not getattr(cfg, 'RESTRICT_SCORE', False):
            score += trend_score * self.weights["trend"]
            features["trend_score"] = trend_score

        supertrend_dir = features.get("supertrend_dir", 0)
        st_score = 0
        if supertrend_dir == 1: st_score = 1
        elif supertrend_dir == -1: st_score = -1

        if not getattr(cfg, 'RESTRICT_SUPERTREND', False) or not getattr(cfg, 'RESTRICT_SCORE', False):
            score += st_score * self.weights.get("trend", 1.0)

        # 6. POI Confluence contribution
        if features.get("poi_active"):
            poi_score = features.get("poi_confluence_score", 0)
            score += (poi_score / 20.0)

        # 7. Trade Delta (Order Flow) contribution
        trade_delta = features.get("trade_delta", 0.0)
        if trade_delta != 0:
            score += trade_delta * 1.5

        # Imbalance Delta contribution
        imb_delta = features.get("imb_delta", 0.0)
        if imb_delta != 0:
            import ta.indicators.book_delta as bd
            score += imb_delta * bd.SCORE_WEIGHT

        price_slope = features.get("mid_slope", 0.0)
        if abs(price_slope) < 0.0001 and abs(imb_delta) > 0.05:
            bonus = 1.0 if imb_delta > 0 else -1.0
            score += bonus

        # 8. Market Structure (BOS vs MSS) contribution
        struct = features.get("structure_signal")
        if struct:
            if "bos" in struct: score += 1.5
            elif "mss" in struct: score += 0.5


        required_min_score = getattr(cfg, 'MIN_REQUIRED_SCORE', 1.5)
        if not features.get("poi_active"):
            required_min_score += 0.5

        if getattr(cfg, 'RESTRICT_SCORE', False) and abs(score) < required_min_score:
            return None

        session = features.get("current_session")
        if session == 'asia':
            if abs(score) < (required_min_score + 1.0):
                return None

        confidence = min(1.0, (abs(score) + 1) / 10)
        if getattr(cfg, 'RESTRICT_CONFIDENCE', False) and confidence < getattr(cfg, 'MIN_CONFIDENCE', 0.66):
            return None

        if getattr(cfg, 'RESTRICT_DIRECTIONAL_SANITY', False):
            if score > 0 and drt < 0.5:
                return None
            if score < 0 and drt > 0.5:
                return None

        if score > 0: direction = "buy"
        elif score < 0: direction = "sell"
        elif imb > 0: direction = "buy"
        elif imb < 0: direction = "sell"
        else: direction = "buy" if drt >= 0.5 else "sell"

        curr_price = features.get("mid", 0)
        session = features.get("current_session")
        if session:
            prev_session = 'asia' if session == 'london' else 'london' if session == 'ny' else 'ny'
            ph = features.get(f"{prev_session}_h", 0)
            pl = features.get(f"{prev_session}_l", 0)

            if ph > 0 and pl > 0:
                dist_h = (ph / curr_price - 1) if curr_price > 0 else 0
                dist_l = (curr_price / pl - 1) if curr_price > 0 else 0

                if direction == "buy" and dist_h > 0 and dist_h < 0.01:
                    score += 0.5
                elif direction == "sell" and dist_l > 0 and dist_l < 0.01:
                    score -= 0.5

        gate_direction = direction
        if getattr(cfg, 'CONTRARIAN_GLOBAL', False) and getattr(cfg, 'CONTRARIAN_FILTER', False):
            gate_direction = "sell" if direction == "buy" else "buy"

        if getattr(cfg, 'RESTRICT_STRUCTURE', False):
            if not struct:
                return None
            if gate_direction == "buy" and "bullish" not in struct:
                return None
            if gate_direction == "sell" and "bearish" not in struct:
                return None

        if getattr(cfg, 'RESTRICT_SUPERTREND', False) and supertrend_dir != 0:
            if gate_direction == "buy" and supertrend_dir != 1:
                return None
            if gate_direction == "sell" and supertrend_dir != -1:
                return None

        if getattr(cfg, 'RESTRICT_MACD', False):
            if gate_direction == "buy" and macd_hist <= 0:
                return None
            if gate_direction == "sell" and macd_hist >= 0:
                return None

        if getattr(cfg, 'RESTRICT_15M_TREND', False):
            if gate_direction == "buy" and asset_15m <= 0:
                return None
            if gate_direction == "sell" and asset_15m >= 0:
                return None

        is_momentum_rider = False
        if getattr(cfg, 'RESTRICT_RSI', False):
            upper_limit = rsi_ind.SHORT_THRESHOLD
            lower_limit = rsi_ind.LONG_THRESHOLD

            if getattr(cfg, 'USE_ADAPTIVE_RSI', False):
                drt_f = features.get("drt_fast", 0.5)
                if gate_direction == "buy" and drt_f < 0.6:
                    lower_limit = rsi_ind.TIGHT_LONG
                elif gate_direction == "sell" and drt_f > 0.4:
                    upper_limit = rsi_ind.TIGHT_SHORT

            if gate_direction == "buy":
                if rsi > lower_limit:
                    return None
                adx = features.get("adx", 0.0)
                if rsi < rsi_ind.BUY_FLOOR and adx > STRONG_TREND_THRESHOLD:
                    is_momentum_rider = True
            if gate_direction == "sell":
                if rsi < upper_limit:
                    return None
                adx = features.get("adx", 0.0)
                if getattr(cfg, 'RESTRICT_RSI_SHORT_CEILING', False) and rsi > rsi_ind.SHORT_CEILING and adx > STRONG_TREND_THRESHOLD:
                    is_momentum_rider = True

        if getattr(cfg, 'USE_DRT_VELOCITY', False):
            drt_active = features.get("drt", 0.5)
            drt_fast = features.get("drt_fast", 0.5)
            if gate_direction == "buy" and drt_active <= drt_fast:
                return None
            if gate_direction == "sell" and drt_active >= drt_fast:
                return None

        if getattr(cfg, 'RESTRICT_BTC_MOMENTUM', False):
            btc_15m = features.get("btc_15m", 0)
            btc_mom_thresh = getattr(cfg, 'BTC_MOMENTUM_THRESHOLD', 0.001)
            if gate_direction == "buy" and btc_15m < -btc_mom_thresh:
                return None
            if gate_direction == "sell" and btc_15m > btc_mom_thresh:
                return None

        if getattr(cfg, 'RESTRICT_BTC_CONFLUENCE', False):
            btc_15m = features.get("btc_15m", 0)
            btc_1h = features.get("btc_1h", 0)
            btc_conf_15m_min = getattr(cfg, 'BTC_CONF_15M_MIN', 0.0002)
            btc_conf_1h_min = getattr(cfg, 'BTC_CONF_1H_MIN', 0.0002)
            if gate_direction == "buy":
                if btc_15m < btc_conf_15m_min or btc_1h < btc_conf_1h_min:
                    return None
            else:
                if btc_15m > -btc_conf_15m_min or btc_1h > -btc_conf_1h_min:
                    return None

        if getattr(cfg, 'RESTRICT_VOLUME_INFLUX', True):
            vol_influx = features.get("volume_influx", False)
            vol_spike = features.get("volume_spike", False)
            if not vol_influx and not vol_spike:
                return None

        if getattr(cfg, 'RESTRICT_HTF_BIAS', True):
            from ta.patterns.trend import NEUTRAL_ALLOWS_TRADES
            bias = features.get("bias", "neutral")
            if bias != "neutral" or not NEUTRAL_ALLOWS_TRADES:
                if gate_direction == "buy" and bias == "bearish":
                    return None
                if gate_direction == "sell" and bias == "bullish":
                    return None

        if getattr(cfg, 'RESTRICT_ASSET_CONFLUENCE', False):
            asset_15m = features.get("asset_15m", 0)
            if gate_direction == "buy" and asset_15m < 0:
                return None
            if gate_direction == "sell" and asset_15m > 0:
                return None

        contrarian_global = getattr(cfg, 'CONTRARIAN_GLOBAL', False)
        if contrarian_global:
            direction = "sell" if original_direction == "buy" else "buy"

        entry = book.best_ask if direction == "buy" else book.best_bid
        max_lev = self.simulator.leverage_limits.get(symbol, 125)

        entry_fee_rate = getattr(cfg, 'MAKER_FEE', 0.0002) if getattr(cfg, 'ENTRY_ORDER_TYPE', 'limit') == "limit" else getattr(cfg, 'TAKER_FEE', 0.0006)
        tp_exit_fee_rate = getattr(cfg, 'MAKER_FEE', 0.0002) if getattr(cfg, 'TP_ORDER_TYPE', 'limit') == "limit" else getattr(cfg, 'TAKER_FEE', 0.0006)
        sl_exit_fee_rate = getattr(cfg, 'MAKER_FEE', 0.0002) if getattr(cfg, 'SL_ORDER_TYPE', 'limit') == "limit" else getattr(cfg, 'TAKER_FEE', 0.0006)

        sl_mult = atr_ind.SL_MULT

        regime = features.get("vol_regime", "Stable")
        forecast = features.get("vol_forecast", "Neutral")

        if regime == "Expansion" or forecast == "Expanding":
            sl_mult *= 1.25
        elif regime == "Contraction" or forecast == "Compressing":
            sl_mult *= 0.75

        if is_momentum_rider:
            sl_mult *= 0.5

        if getattr(cfg, 'USE_ATR_SL', False) and features.get("atr"):
            sl_move = (features["atr"] * sl_mult) / entry
        else:
            sl_move = getattr(cfg, 'SL_MOVE', 0.004) * (0.5 if is_momentum_rider else 1.0)

        sl_floor = max(0.001, getattr(cfg, 'MAX_SPREAD_PCT', 0.002) * 1.5)
        sl_move = max(sl_move, sl_floor)

        net_sl_cost = sl_move + entry_fee_rate + sl_exit_fee_rate
        target_roe = 0.20
        tp_move_from_roe = (target_roe / max_lev) + entry_fee_rate + tp_exit_fee_rate + getattr(cfg, 'EXPECTED_SLIPPAGE', 0.001)
        tp_move = max(tp_move_from_roe, (net_sl_cost * 2) + entry_fee_rate + tp_exit_fee_rate + getattr(cfg, 'EXPECTED_SLIPPAGE', 0.001))

        if getattr(cfg, 'USE_TP_RELAXATION', True):
            drt_offset = abs(features.get("drt", 0.5) - 0.5)
            if drt_offset < getattr(cfg, 'TP_RELAXATION_THRESHOLD', 0.05):
                tp_move = (net_sl_cost * 1.5) + entry_fee_rate + tp_exit_fee_rate + getattr(cfg, 'EXPECTED_SLIPPAGE', 0.001)

        asset_regime = features.get("asset_regime", "stable")
        tp_mult = 1.0
        if asset_regime == 'high_beta':
            tp_mult = 1.5
        elif asset_regime == 'major':
            tp_mult = 0.8

        if getattr(cfg, 'USE_ATR_CAPPED_TP', False) and features.get("atr"):
            atr_15m_move = (features["atr"] * 3.8 * tp_mult) / entry
            tp_move = min(tp_move, atr_15m_move)

        tp_move = max(tp_move, getattr(cfg, 'TP_MOVE', 0.008) * tp_mult)

        net_tp_win = tp_move - entry_fee_rate - tp_exit_fee_rate - getattr(cfg, 'EXPECTED_SLIPPAGE', 0.001)
        sl_move_target = (net_tp_win / 2) - entry_fee_rate - sl_exit_fee_rate

        if sl_move_target < sl_floor:
            sl_move = sl_floor
            tp_move = (net_sl_cost * 2) + entry_fee_rate + tp_exit_fee_rate + getattr(cfg, 'EXPECTED_SLIPPAGE', 0.001)
        else:
            sl_move = sl_move_target

        if direction == "buy":
            exit_price = entry * (1 + tp_move)
            stop_price = entry * (1 - sl_move)
        else:
            exit_price = entry * (1 - tp_move)
            stop_price = entry * (1 + sl_move)

        expected_wr = 0.35 + (confidence - 0.5) * 0.2
        expected_r = (net_tp_win / (net_sl_cost + 1e-9))

        risk_fraction = calculate_kelly_size(expected_wr, expected_r, kelly_fraction=0.5)

        if getattr(cfg, 'USE_VOL_ADJUSTED_RISK', False):
            atr_pct = features.get("atr", 0) / entry if entry > 0 else 0
            if atr_pct > atr_ind.VOL_ADJUST_THRESHOLD:
                risk_fraction = getattr(cfg, 'RISK_PER_TRADE', 0.005) * atr_ind.REDUCED_RISK_FRACTION

        kz = features.get("killzone")
        if kz in ["london", "ny_am"]:
            risk_fraction *= getattr(cfg, 'SESSION_MULTIPLIER', 1.5)

        starting_equity = getattr(cfg, 'INITIAL_EQUITY', 15.0)
        reinvest_pct = getattr(cfg, 'REINVESTMENT_PERCENTAGE', 1.0)

        if equity > starting_equity:
            riskable_equity = starting_equity + (equity - starting_equity) * reinvest_pct
        else:
            riskable_equity = equity

        qty = calculate_position_size(
            riskable_equity,
            risk_fraction,
            entry,
            stop_price,
            entry_maker=(getattr(cfg, 'ENTRY_ORDER_TYPE', 'limit') == "limit"),
            exit_maker=(getattr(cfg, 'SL_ORDER_TYPE', 'limit') == "limit"),
            fee_aware=getattr(cfg, 'FEE_AWARE_SIZING', True)
        )

        spec = self.simulator.contract_specs.get(symbol, {})
        vol_place = int(spec.get('volumePlace', 3))
        price_place = int(spec.get('pricePlace', 2))

        qty = math.floor(qty * (10 ** vol_place)) / (10 ** vol_place)
        if qty <= 0:
            return None

        entry = round(entry, price_place)
        exit_price = round(exit_price, price_place)
        stop_price = round(stop_price, price_place)

        tp1_price = None
        tp1_qty = 0
        tp2_qty = qty
        if getattr(cfg, 'USE_BREAKEVEN_TRIGGER', False) and getattr(cfg, 'EXIT_STRATEGY', 'BE+TP1+TP2') == "BE+TP1+TP2":
            be_move = (entry_fee_rate + getattr(cfg, 'MAKER_FEE', 0.0002)) + (getattr(cfg, 'BREAKEVEN_PROFIT_BUFFER', 0.05) / max_lev)
            if direction == "buy":
                be_price = entry * (1 + be_move)
                distance = exit_price - be_price
                tp1_price = be_price + (distance * getattr(cfg, 'TP1_BUFFER_PCT', 0.5))
            else:
                be_price = entry * (1 - be_move)
                distance = be_price - exit_price
                tp1_price = be_price - (distance * getattr(cfg, 'TP1_BUFFER_PCT', 0.5))

            tp1_price = round(tp1_price, price_place)
            tp1_qty = math.floor(qty * getattr(cfg, 'TP1_QTY_RATIO', 0.5) * (10 ** vol_place)) / (10 ** vol_place)
            tp2_qty = round(qty - tp1_qty, vol_place)

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
            "tp1_price": tp1_price,
            "tp2_price": exit_price,
            "tp1_qty": tp1_qty,
            "tp2_qty": tp2_qty,
            "confidence": confidence,
            "btc_confluence": btc_conf,
            "original_side": original_direction,
            "is_contrarian": getattr(cfg, 'CONTRARIAN_GLOBAL', False)
        }

        drt_fast = features.get("drt_fast", 0.5)
        drt_slow = features.get("drt_slow", 0.5)
        premium_fast = "PREM" if drt_fast > 0.5 else "DISC"
        premium_slow = "PREM" if drt_slow > 0.5 else "DISC"

        signal.update(features)
        signal.update({
            "rsi": rsi,
            "drt_f": f"{drt_fast:.4f}({premium_fast})",
            "drt_s": f"{drt_slow:.4f}({premium_slow})",
        })
        return signal

class DummyModel:
    def predict(self, symbol, book, equity=None):
        return None

    def train_on_tick(self, symbol, features, direction_up):
        pass

    def train_on_trade(self, symbol, features, pnl):
        pass
