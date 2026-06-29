import math
import logging
import config
from tools.trading_utils import calculate_position_size, calculate_tp_for_roe
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
        self.lr = 0.0 # Disabled as per user request "Not yet"

    def train_on_tick(self, symbol, prev_features, actual_up):
        # online learning toggle check
        if not getattr(config, 'USE_ONLINE_LEARNING', False):
            return

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
        # Use locally namespaced threshold from drt_pat
        if getattr(config, 'RESTRICT_DRT', False) and trend_offset < drt_pat.STRENGTH_MIN:
            log.debug(f"REJECT {symbol}: Trend strength {trend_offset:.4f} < {drt_pat.STRENGTH_MIN}")
            return None

        imb = features.get("imbalance", 0)
        # 2. Imbalance filter
        if getattr(config, 'RESTRICT_IMBALANCE', True) and abs(imb) < flow_ind.MIN_IMBALANCE:
            log.debug(f"REJECT {symbol}: Imbalance {imb:.4f} < {flow_ind.MIN_IMBALANCE}")
            return None

        # 3. Liquidity/Volume filter
        vol_pct = features.get("vol_pct", 0)
        if getattr(config, 'RESTRICT_VOL_PCT', False) and vol_pct < flow_ind.VOL_PCT_MIN:
            log.debug(f"REJECT {symbol}: Volatility pct {vol_pct:.4f} < {flow_ind.VOL_PCT_MIN}")
            return None

        # 4. Spread filter
        mid = features.get("mid", 0)
        book_bid, book_ask = book.best_bid, book.best_ask
        spread_pct = (book_ask - book_bid) / mid if mid > 0 else 0
        if getattr(config, 'RESTRICT_SPREAD', False) and spread_pct > getattr(config, 'MAX_SPREAD_PCT', 0.002):
            log.debug(f"REJECT {symbol}: Spread pct {spread_pct:.4f} > {getattr(config, 'MAX_SPREAD_PCT', 0.002)}")
            return None

        # 5. ATR filter
        atr = features.get("atr", 0)
        if getattr(config, 'RESTRICT_ATR', False) and atr < atr_ind.MIN_VOLATILITY:
            log.debug(f"REJECT {symbol}: ATR {atr:.8f} < {atr_ind.MIN_VOLATILITY}")
            return None

        # --- SCORING WITH LEARNED WEIGHTS ---
        score = 0

        # Imbalance contribution
        imb_score = 0
        if imb > 0.10: imb_score = 2
        elif imb > flow_ind.MIN_IMBALANCE: imb_score = 1
        elif imb < -0.10: imb_score = -2
        elif imb < -flow_ind.MIN_IMBALANCE: imb_score = -1

        if getattr(config, 'RESTRICT_IMBALANCE', True) or not getattr(config, 'RESTRICT_SCORE', False):
            score += imb_score * self.weights["imbalance"]

        # RSI contribution
        rsi = features.get("rsi", 50)
        rsi_score = 0
        if rsi < rsi_ind.LONG_THRESHOLD: rsi_score = 1
        elif rsi > rsi_ind.SHORT_THRESHOLD: rsi_score = -1

        if getattr(config, 'RESTRICT_RSI', False) or not getattr(config, 'RESTRICT_SCORE', False):
            score += rsi_score * self.weights["rsi"]

        # MACD contribution
        macd_hist = features.get("macd_hist", 0)
        macd_score = 0
        if macd_hist > 0: macd_score = 1
        elif macd_hist < 0: macd_score = -1

        if getattr(config, 'RESTRICT_MACD', False) or not getattr(config, 'RESTRICT_SCORE', False):
            score += macd_score * self.weights["macd"]

        # Trend/Confluence contribution
        asset_15m = features.get("asset_15m", 0)
        trend_score = 0
        trend_15m_min = getattr(config, 'TREND_15M_MIN', 0.0001)
        if asset_15m > trend_15m_min: trend_score = 1
        elif asset_15m < -trend_15m_min: trend_score = -1

        if getattr(config, 'RESTRICT_15M_TREND', False) or not getattr(config, 'RESTRICT_SCORE', False):
            score += trend_score * self.weights["trend"]

        # Supertrend contribution (Scoring instead of Hard Gate)
        supertrend_dir = features.get("supertrend_dir", 0)
        st_score = 0
        if supertrend_dir == 1: st_score = 1
        elif supertrend_dir == -1: st_score = -1

        if not getattr(config, 'RESTRICT_SUPERTREND', False) or not getattr(config, 'RESTRICT_SCORE', False):
            score += st_score * self.weights.get("trend", 1.0)

        # 6. POI Confluence contribution
        if features.get("poi_active"):
            poi_score = features.get("poi_confluence_score", 0)
            score += (poi_score / 20.0) # Scale 40 points -> +2 score
            log.debug(f"POI Confluence active for {symbol}: +{poi_score/20.0:.1f} score")

        # 7. Trade Delta (Order Flow) contribution
        trade_delta = features.get("trade_delta", 0.0)
        if trade_delta != 0:
            score += trade_delta * 1.5 # High weight for aggressive flow
            log.debug(f"Trade Delta (Order Flow) for {symbol}: {trade_delta:.2f} (added to score)")

        # [OP-001] Imbalance Delta contribution
        imb_delta = features.get("imb_delta", 0.0)
        if imb_delta != 0:
            import ta.indicators.book_delta as bd
            score += imb_delta * bd.SCORE_WEIGHT
            log.debug(f"Imbalance Delta for {symbol}: {imb_delta:.4f} (added to score)")

        # 8. Market Structure (BOS vs MSS) contribution
        struct = features.get("structure_signal")
        if struct:
            if "bos" in struct: score += 1.5
            elif "mss" in struct: score += 0.5
            log.debug(f"Market Structure signal {struct} for {symbol}: added bonus score")


        # Check for trade signal
        required_min_score = getattr(config, 'MIN_REQUIRED_SCORE', 1.5)
        if not features.get("poi_active"):
            # Require higher score if not at a POI
            required_min_score += 0.5

        if getattr(config, 'RESTRICT_SCORE', False) and abs(score) < required_min_score:
            log.debug(f"REJECT {symbol}: Score {score:.1f} < {required_min_score}")
            return None

        # [OP-006] Session-Specific Logic Profiles
        session = features.get("current_session")
        if session == 'asia':
            # Be more selective in Asian session (range bound)
            if abs(score) < (required_min_score + 1.0):
                log.debug(f"REJECT {symbol}: Asian session requires higher score ({required_min_score + 1.0})")
                return None

        # Confidence calculation
        confidence = min(1.0, (abs(score) + 1) / 10)
        if getattr(config, 'RESTRICT_CONFIDENCE', False) and confidence < getattr(config, 'MIN_CONFIDENCE', 0.66):
            log.debug(f"REJECT {symbol}: Confidence {confidence:.2f} < {getattr(config, 'MIN_CONFIDENCE', 0.66)}")
            return None

        # Direction check: ensure scoring matches the DRT trend
        if getattr(config, 'RESTRICT_DIRECTIONAL_SANITY', False):
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

        # --- CONTRARIAN FILTER LOGIC ---
        # If CONTRARIAN_FILTER is True, we flip the INTENDED direction for all hard gates
        # This means we approval a "Buy" based on "Sell" criteria.
        gate_direction = direction
        if getattr(config, 'CONTRARIAN_GLOBAL', False) and getattr(config, 'CONTRARIAN_FILTER', False):
            gate_direction = "sell" if direction == "buy" else "buy"

        # [OP-007] Structure-First Trigger Logic
        if getattr(config, 'RESTRICT_STRUCTURE', False):
            if not struct:
                log.debug(f"REJECT {symbol}: No market structure signal detected")
                return None
            if gate_direction == "buy" and "bullish" not in struct:
                log.debug(f"REJECT {symbol}: Bullish entry requested but structure is {struct}")
                return None
            if gate_direction == "sell" and "bearish" not in struct:
                log.debug(f"REJECT {symbol}: Bearish entry requested but structure is {struct}")
                return None

        # Hard Gates for restricted indicators
        # Supertrend filter (Conditional Hard Gate)
        if getattr(config, 'RESTRICT_SUPERTREND', False) and supertrend_dir != 0:
            if gate_direction == "buy" and supertrend_dir != 1:
                log.debug(f"REJECT {symbol}: Supertrend bearish for {gate_direction}")
                return None
            if gate_direction == "sell" and supertrend_dir != -1:
                log.debug(f"REJECT {symbol}: Supertrend bullish for {gate_direction}")
                return None

        if getattr(config, 'RESTRICT_MACD', False):
            if gate_direction == "buy" and macd_hist <= 0:
                log.debug(f"REJECT {symbol}: MACD bearish for {gate_direction}")
                return None
            if gate_direction == "sell" and macd_hist >= 0:
                log.debug(f"REJECT {symbol}: MACD bullish for {gate_direction}")
                return None

        if getattr(config, 'RESTRICT_15M_TREND', False):
            if gate_direction == "buy" and asset_15m <= 0:
                log.debug(f"REJECT {symbol}: 15m trend bearish for {gate_direction}")
                return None
            if gate_direction == "sell" and asset_15m >= 0:
                log.debug(f"REJECT {symbol}: 15m trend bullish for {gate_direction}")
                return None

        # RSI Restrictions and Momentum Rider Logic
        is_momentum_rider = False
        if getattr(config, 'RESTRICT_RSI', False):
            # 1. Adaptive RSI Logic
            upper_limit = rsi_ind.SHORT_THRESHOLD
            lower_limit = rsi_ind.LONG_THRESHOLD

            if getattr(config, 'USE_ADAPTIVE_RSI', False):
                drt_f = features.get("drt_fast", 0.5)
                # If momentum is not extreme (>0.6 or <0.4), use TIGHT filters
                if gate_direction == "buy" and drt_f < 0.6:
                    lower_limit = rsi_ind.TIGHT_LONG
                elif gate_direction == "sell" and drt_f > 0.4:
                    upper_limit = rsi_ind.TIGHT_SHORT

            if gate_direction == "buy":
                if rsi > lower_limit:
                    log.debug(f"REJECT {symbol}: RSI {rsi:.1f} > {lower_limit} (Adaptive {gate_direction})")
                    return None
                # [OP-004] ADX-Based Momentum Rider
                adx = features.get("adx", 0.0)
                if rsi < rsi_ind.BUY_FLOOR and adx > STRONG_TREND_THRESHOLD:
                    # Instead of blocking, trigger Momentum Rider
                    is_momentum_rider = True
                    log.debug(f"MOMENTUM RIDER ACTIVE for {symbol} (Long): RSI {rsi:.1f} < {rsi_ind.BUY_FLOOR} and ADX {adx:.1f}")
            if gate_direction == "sell":
                if rsi < upper_limit:
                    log.debug(f"REJECT {symbol}: RSI {rsi:.1f} < {upper_limit} (Adaptive {gate_direction})")
                    return None
                adx = features.get("adx", 0.0)
                if getattr(config, 'RESTRICT_RSI_SHORT_CEILING', False) and rsi > rsi_ind.SHORT_CEILING and adx > STRONG_TREND_THRESHOLD:
                    # Instead of blocking, trigger Momentum Rider
                    is_momentum_rider = True
                    log.debug(f"MOMENTUM RIDER ACTIVE for {symbol} (Short): RSI {rsi:.1f} > {rsi_ind.SHORT_CEILING} and ADX {adx:.1f}")

        # DRT Velocity Check
        if getattr(config, 'USE_DRT_VELOCITY', False):
            drt_active = features.get("drt", 0.5)
            drt_fast = features.get("drt_fast", 0.5)
            if gate_direction == "buy" and drt_active <= drt_fast:
                log.debug(f"REJECT {symbol}: DRT velocity negative for {gate_direction} ({drt_active:.4f} <= {drt_fast:.4f})")
                return None
            if gate_direction == "sell" and drt_active >= drt_fast:
                log.debug(f"REJECT {symbol}: DRT velocity positive for {gate_direction} ({drt_active:.4f} >= {drt_fast:.4f})")
                return None

        # BTC Confluence Restrictions
        if getattr(config, 'RESTRICT_BTC_MOMENTUM', False):
            btc_15m = features.get("btc_15m", 0)
            btc_mom_thresh = getattr(config, 'BTC_MOMENTUM_THRESHOLD', 0.001)
            if gate_direction == "buy" and btc_15m < -btc_mom_thresh:
                log.debug(f"REJECT {symbol}: BTC 15m bearish {btc_15m:.4f} < -{btc_mom_thresh}")
                return None
            if gate_direction == "sell" and btc_15m > btc_mom_thresh:
                log.debug(f"REJECT {symbol}: BTC 15m bullish {btc_15m:.4f} > {btc_mom_thresh}")
                return None

        if getattr(config, 'RESTRICT_BTC_CONFLUENCE', False):
            # [OP-005] Stabilize BTC Confluence: Ignore 1m noise
            btc_15m = features.get("btc_15m", 0)
            btc_1h = features.get("btc_1h", 0)
            btc_conf_15m_min = getattr(config, 'BTC_CONF_15M_MIN', 0.0002)
            btc_conf_1h_min = getattr(config, 'BTC_CONF_1H_MIN', 0.0002)
            if gate_direction == "buy":
                if btc_15m < btc_conf_15m_min or btc_1h < btc_conf_1h_min:
                    log.debug(f"REJECT {symbol}: BTC 15m/1h [{btc_15m:.4f}/{btc_1h:.4f}] < {btc_conf_15m_min} for {gate_direction}")
                    return None
            else: # sell
                if btc_15m > -btc_conf_15m_min or btc_1h > -btc_conf_1h_min:
                    log.debug(f"REJECT {symbol}: BTC 15m/1h [{btc_15m:.4f}/{btc_1h:.4f}] > {-btc_conf_15m_min} for {gate_direction}")
                    return None

        # Volume Influx Confirmation Gate
        if getattr(config, 'RESTRICT_VOLUME_INFLUX', True):
            vol_influx = features.get("volume_influx", False)
            vol_spike = features.get("volume_spike", False)
            if not vol_influx and not vol_spike:
                log.debug(f"REJECT {symbol}: No volume influx or spike confirmed")
                return None

        # HTF Bias Alignment Gate
        if getattr(config, 'RESTRICT_HTF_BIAS', True):
            from ta.patterns.trend import NEUTRAL_ALLOWS_TRADES
            bias = features.get("bias", "neutral")
            if bias != "neutral" or not NEUTRAL_ALLOWS_TRADES:
                if gate_direction == "buy" and bias == "bearish":
                    log.debug(f"REJECT {symbol}: Long entry against BEARISH HTF bias")
                    return None
                if gate_direction == "sell" and bias == "bullish":
                    log.debug(f"REJECT {symbol}: Short entry against BULLISH HTF bias")
                    return None

        # Asset Confluence (15m alignment)
        if getattr(config, 'RESTRICT_ASSET_CONFLUENCE', False):
            asset_15m = features.get("asset_15m", 0)
            if gate_direction == "buy" and asset_15m < 0:
                log.debug(f"REJECT {symbol}: Asset 15m negative momentum {asset_15m:.4f} for {gate_direction}")
                return None
            if gate_direction == "sell" and asset_15m > 0:
                log.debug(f"REJECT {symbol}: Asset 15m positive momentum {asset_15m:.4f} for {gate_direction}")
                return None

        # --- CONTRARIAN GLOBAL EXECUTION ---
        original_direction = direction
        contrarian_global = getattr(config, 'CONTRARIAN_GLOBAL', False)
        if contrarian_global:
            # Flip the final order direction
            direction = "sell" if original_direction == "buy" else "buy"

        entry = book.best_ask if direction == "buy" else book.best_bid
        max_lev = self.simulator.leverage_limits.get(symbol, 125)

        # Dynamic TP/SL calculation
        entry_fee_rate = getattr(config, 'MAKER_FEE', 0.0002) if getattr(config, 'ENTRY_ORDER_TYPE', 'limit') == "limit" else getattr(config, 'TAKER_FEE', 0.0006)
        tp_exit_fee_rate = getattr(config, 'MAKER_FEE', 0.0002) if getattr(config, 'TP_ORDER_TYPE', 'limit') == "limit" else getattr(config, 'TAKER_FEE', 0.0006)
        sl_exit_fee_rate = getattr(config, 'MAKER_FEE', 0.0002) if getattr(config, 'SL_ORDER_TYPE', 'limit') == "limit" else getattr(config, 'TAKER_FEE', 0.0006)

        # 1. Calculate Base SL_MOVE (Volatility-aware or config fallback)
        sl_mult = atr_ind.SL_MULT

        # Volatility Regime & Forecast Adjustments [OP-002]
        regime = features.get("vol_regime", "Stable")
        forecast = features.get("vol_forecast", "Neutral")

        if regime == "Expansion" or forecast == "Expanding":
            sl_mult *= 1.25 # Widen for expansion
        elif regime == "Contraction" or forecast == "Compressing":
            sl_mult *= 0.75 # Tighten for contraction

        if is_momentum_rider:
            sl_mult *= 0.5 # Tighten stops by 50% for momentum riding

        if getattr(config, 'USE_ATR_SL', False) and features.get("atr"):
            sl_move = (features["atr"] * sl_mult) / entry
        else:
            sl_move = getattr(config, 'SL_MOVE', 0.004) * (0.5 if is_momentum_rider else 1.0)

        sl_move = max(sl_move, 0.001)

        # 2. Synchronize TP_MOVE to maintain the 1:2 Net RRR
        net_sl_cost = sl_move + entry_fee_rate + sl_exit_fee_rate
        tp_move_from_roe = (getattr(config, 'TARGET_NET_ROE', 0.20) / max_lev) + entry_fee_rate + tp_exit_fee_rate + getattr(config, 'EXPECTED_SLIPPAGE', 0.001)
        tp_move = max(tp_move_from_roe, (net_sl_cost * 2) + entry_fee_rate + tp_exit_fee_rate + getattr(config, 'EXPECTED_SLIPPAGE', 0.001))

        # 3. Apply TP Relaxation if needed (reduces RRR to 1.5:1 if flat)
        if getattr(config, 'USE_TP_RELAXATION', True):
            drt_offset = abs(features.get("drt", 0.5) - 0.5)
            if drt_offset < getattr(config, 'TP_RELAXATION_THRESHOLD', 0.05):
                tp_move = (net_sl_cost * 1.5) + entry_fee_rate + tp_exit_fee_rate + getattr(config, 'EXPECTED_SLIPPAGE', 0.001)
                log.debug(f"TP RELAXED for {symbol}: using 1.5:1 RRR due to flat DRT ({drt_offset:.4f})")

        # 4. Final Caps and Floors
        if getattr(config, 'USE_ATR_CAPPED_TP', False) and features.get("atr"):
            atr_15m_move = (features["atr"] * 3.8) / entry
            tp_move = min(tp_move, atr_15m_move)

        tp_move = max(tp_move, getattr(config, 'TP_MOVE', 0.008))

        # 5. Final SL Recalibration
        net_tp_win = tp_move - entry_fee_rate - tp_exit_fee_rate - getattr(config, 'EXPECTED_SLIPPAGE', 0.001)
        sl_move = (net_tp_win / 2) - entry_fee_rate - sl_exit_fee_rate
        sl_move = max(sl_move, 0.001)

        if direction == "buy":
            exit_price = entry * (1 + tp_move)
            stop_price = entry * (1 - sl_move)
        else:
            exit_price = entry * (1 - tp_move)
            stop_price = entry * (1 + sl_move)

        # --- VOL-ADJUSTED RISK LOGIC ---
        risk_fraction = getattr(config, 'RISK_PER_TRADE', 0.005)
        if getattr(config, 'USE_VOL_ADJUSTED_RISK', False):
            atr_pct = features.get("atr", 0) / entry if entry > 0 else 0
            if atr_pct > atr_ind.VOL_ADJUST_THRESHOLD:
                risk_fraction = getattr(config, 'RISK_PER_TRADE', 0.005) * atr_ind.REDUCED_RISK_FRACTION
                log.debug(f"RISK REDUCED for {symbol}: ATR {atr_pct:.4f} > {atr_ind.VOL_ADJUST_THRESHOLD}")

        kz = features.get("killzone")
        if kz in ["london", "ny_am"]:
            risk_fraction *= getattr(config, 'SESSION_MULTIPLIER', 1.5)

        # Centralized Position Sizing
        qty = calculate_position_size(
            equity,
            risk_fraction,
            entry,
            stop_price,
            entry_maker=(getattr(config, 'ENTRY_ORDER_TYPE', 'limit') == "limit"),
            exit_maker=(getattr(config, 'SL_ORDER_TYPE', 'limit') == "limit"),
            fee_aware=getattr(config, 'FEE_AWARE_SIZING', True)
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

        # Multi-Stage TP Calculation
        tp1_price = None
        tp1_qty = 0
        tp2_qty = qty
        if getattr(config, 'USE_BREAKEVEN_TRIGGER', False) and getattr(config, 'EXIT_STRATEGY', 'BE+TP1+TP2') == "BE+TP1+TP2":
            be_move = (entry_fee_rate + getattr(config, 'MAKER_FEE', 0.0002)) + (getattr(config, 'BREAKEVEN_PROFIT_BUFFER', 0.05) / max_lev)
            if direction == "buy":
                be_price = entry * (1 + be_move)
                distance = exit_price - be_price
                tp1_price = be_price + (distance * getattr(config, 'TP1_BUFFER_PCT', 0.5))
            else:
                be_price = entry * (1 - be_move)
                distance = be_price - exit_price
                tp1_price = be_price - (distance * getattr(config, 'TP1_BUFFER_PCT', 0.5))

            tp1_price = round(tp1_price, price_place)
            tp1_qty = math.floor(qty * getattr(config, 'TP1_QTY_RATIO', 0.5) * (10 ** vol_place)) / (10 ** vol_place)
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
            "is_contrarian": getattr(config, 'CONTRARIAN_GLOBAL', False)
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
