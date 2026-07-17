import math
import logging
import config
from ta.scoring import ScoringEngine
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

        se = ScoringEngine()
        buy_res = se.evaluate(features, side="buy", config_context=cfg, dynamic_weights=self.weights)
        sell_res = se.evaluate(features, side="sell", config_context=cfg, dynamic_weights=self.weights)

        if hasattr(self.simulator, "engine") and self.simulator.engine:
            self.simulator.engine._write_metrics_log(symbol, "buy", "model", buy_res)
            self.simulator.engine._write_metrics_log(symbol, "sell", "model", sell_res)

        direction = None
        scoring_result = None

        buy_passed = (buy_res["decision"] == "TAKEN")
        sell_passed = (sell_res["decision"] == "TAKEN")
        report_only = getattr(cfg, 'BY_DEFAULT_REPORT_ONLY', True)

        if report_only:
            abs_buy = abs(buy_res["aggregated_score"])
            abs_sell = abs(sell_res["aggregated_score"])
            if abs_buy >= abs_sell:
                direction = "buy"
                scoring_result = buy_res
            else:
                direction = "sell"
                scoring_result = sell_res
        else:
            if buy_passed and sell_passed:
                if buy_res["aggregated_score"] >= abs(sell_res["aggregated_score"]):
                    direction = "buy"
                    scoring_result = buy_res
                else:
                    direction = "sell"
                    scoring_result = sell_res
            elif buy_passed:
                direction = "buy"
                scoring_result = buy_res
            elif sell_passed:
                direction = "sell"
                scoring_result = sell_res
            else:
                return None

        # Determine if we are momentum riding
        is_momentum_rider = False
        adx = features.get("adx", 0.0)
        rsi = features.get("rsi", 50.0)
        if direction == "buy" and rsi < rsi_ind.BUY_FLOOR and adx > STRONG_TREND_THRESHOLD:
            is_momentum_rider = True
        elif direction == "sell" and rsi > rsi_ind.SHORT_CEILING and adx > STRONG_TREND_THRESHOLD:
            is_momentum_rider = True

        original_direction = direction
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
        target_roe = getattr(cfg, "TARGET_NET_ROE", 0.20)
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

        confidence = features.get("confidence", 0.5) if features.get("confidence") is not None else 0.5
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
