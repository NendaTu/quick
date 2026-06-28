import math
import logging
from config import *
from ta.indicators.rsi import compute_rsi
from ta.indicators.macd import compute_macd
from ta.indicators.ema import compute_ema
from ta.indicators.supertrend import compute_supertrend
from ta.patterns.drt import compute_drt

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

        # 3. Liquidity/Volume filter
        vol_pct = features.get("vol_pct", 0)
        if RESTRICT_VOL_PCT and vol_pct < VOL_PCT_MIN:
            log.debug(f"REJECT {symbol}: Volatility pct {vol_pct:.4f} < {VOL_PCT_MIN}")
            return None

        # 4. Spread filter
        mid = features.get("mid", 0)
        book_bid, book_ask = book.best_bid, book.best_ask
        spread_pct = (book_ask - book_bid) / mid if mid > 0 else 0
        if RESTRICT_SPREAD and spread_pct > MAX_SPREAD_PCT:
            log.debug(f"REJECT {symbol}: Spread pct {spread_pct:.4f} > {MAX_SPREAD_PCT}")
            return None

        # 5. ATR filter
        atr = features.get("atr", 0)
        if RESTRICT_ATR and atr < ATR_MIN:
            log.debug(f"REJECT {symbol}: ATR {atr:.8f} < {ATR_MIN}")
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

        # --- CONTRARIAN FILTER LOGIC ---
        # If CONTRARIAN_FILTER is True, we flip the INTENDED direction for all hard gates
        # This means we approval a "Buy" based on "Sell" criteria.
        gate_direction = direction
        if CONTRARIAN_GLOBAL and CONTRARIAN_FILTER:
            gate_direction = "sell" if direction == "buy" else "buy"

        # Hard Gates for restricted indicators
        # Supertrend filter
        supertrend_dir = features.get("supertrend_dir", 0)
        if RESTRICT_SUPERTREND and supertrend_dir != 0:
            if gate_direction == "buy" and supertrend_dir != 1:
                log.debug(f"REJECT {symbol}: Supertrend bearish for {gate_direction}")
                return None
            if gate_direction == "sell" and supertrend_dir != -1:
                log.debug(f"REJECT {symbol}: Supertrend bullish for {gate_direction}")
                return None

        if RESTRICT_MACD:
            if gate_direction == "buy" and macd_hist <= 0:
                log.debug(f"REJECT {symbol}: MACD bearish for {gate_direction}")
                return None
            if gate_direction == "sell" and macd_hist >= 0:
                log.debug(f"REJECT {symbol}: MACD bullish for {gate_direction}")
                return None

        if RESTRICT_15M_TREND:
            if gate_direction == "buy" and asset_15m <= 0:
                log.debug(f"REJECT {symbol}: 15m trend bearish for {gate_direction}")
                return None
            if gate_direction == "sell" and asset_15m >= 0:
                log.debug(f"REJECT {symbol}: 15m trend bullish for {gate_direction}")
                return None

        # RSI Restrictions
        if RESTRICT_RSI:
            # 1. Adaptive RSI Logic
            upper_limit = RSI_SHORT
            lower_limit = RSI_LONG

            if USE_ADAPTIVE_RSI:
                drt_f = features.get("drt_fast", 0.5)
                # If momentum is not extreme (>0.6 or <0.4), use TIGHT filters
                if gate_direction == "buy" and drt_f < 0.6:
                    lower_limit = RSI_TIGHT_LONG
                elif gate_direction == "sell" and drt_f > 0.4:
                    upper_limit = RSI_TIGHT_SHORT

            if gate_direction == "buy":
                if rsi > lower_limit:
                    log.debug(f"REJECT {symbol}: RSI {rsi:.1f} > {lower_limit} (Adaptive {gate_direction})")
                    return None
                if rsi < RSI_BUY_FLOOR:
                    log.debug(f"REJECT {symbol}: RSI {rsi:.1f} < {RSI_BUY_FLOOR} (Floor {gate_direction})")
                    return None
            if gate_direction == "sell":
                if rsi < upper_limit:
                    log.debug(f"REJECT {symbol}: RSI {rsi:.1f} < {upper_limit} (Adaptive {gate_direction})")
                    return None
                if RESTRICT_RSI_SHORT_CEILING and rsi > RSI_SHORT_CEILING:
                    log.debug(f"REJECT {symbol}: RSI {rsi:.1f} > {RSI_SHORT_CEILING} (Ceiling {gate_direction})")
                    return None

        # DRT Velocity Check
        if USE_DRT_VELOCITY:
            drt_active = features.get("drt", 0.5)
            drt_fast = features.get("drt_fast", 0.5)
            if gate_direction == "buy" and drt_active <= drt_fast:
                log.debug(f"REJECT {symbol}: DRT velocity negative for {gate_direction} ({drt_active:.4f} <= {drt_fast:.4f})")
                return None
            if gate_direction == "sell" and drt_active >= drt_fast:
                log.debug(f"REJECT {symbol}: DRT velocity positive for {gate_direction} ({drt_active:.4f} >= {drt_fast:.4f})")
                return None

        # BTC Confluence Restrictions
        if RESTRICT_BTC_MOMENTUM:
            btc_15m = features.get("btc_15m", 0)
            if gate_direction == "buy" and btc_15m < -BTC_MOMENTUM_THRESHOLD:
                log.debug(f"REJECT {symbol}: BTC 15m bearish {btc_15m:.4f} < -{BTC_MOMENTUM_THRESHOLD}")
                return None
            if gate_direction == "sell" and btc_15m > BTC_MOMENTUM_THRESHOLD:
                log.debug(f"REJECT {symbol}: BTC 15m bullish {btc_15m:.4f} > {BTC_MOMENTUM_THRESHOLD}")
                return None

        if RESTRICT_BTC_CONFLUENCE:
            btc_15m = features.get("btc_15m", 0)
            btc_1h = features.get("btc_1h", 0)
            if gate_direction == "buy":
                if btc_15m < BTC_CONF_15M_MIN or btc_1h < BTC_CONF_1H_MIN:
                    log.debug(f"REJECT {symbol}: BTC 15m/1h [{btc_15m:.4f}/{btc_1h:.4f}] < {BTC_CONF_15M_MIN} for {gate_direction}")
                    return None
            else: # sell
                if btc_15m > -BTC_CONF_15M_MIN or btc_1h > -BTC_CONF_1H_MIN:
                    log.debug(f"REJECT {symbol}: BTC 15m/1h [{btc_15m:.4f}/{btc_1h:.4f}] > {-BTC_CONF_15M_MIN} for {gate_direction}")
                    return None

        # Volume Influx Confirmation Gate
        if RESTRICT_VOLUME_INFLUX:
            vol_influx = features.get("volume_influx", False)
            vol_spike = features.get("volume_spike", False)
            if not vol_influx and not vol_spike:
                log.debug(f"REJECT {symbol}: No volume influx or spike confirmed")
                return None

        # HTF Bias Alignment Gate
        if RESTRICT_HTF_BIAS:
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
        if RESTRICT_ASSET_CONFLUENCE:
            asset_15m = features.get("asset_15m", 0)
            if gate_direction == "buy" and asset_15m < 0:
                log.debug(f"REJECT {symbol}: Asset 15m negative momentum {asset_15m:.4f} for {gate_direction}")
                return None
            if gate_direction == "sell" and asset_15m > 0:
                log.debug(f"REJECT {symbol}: Asset 15m positive momentum {asset_15m:.4f} for {gate_direction}")
                return None

        # --- CONTRARIAN GLOBAL EXECUTION ---
        original_direction = direction
        if CONTRARIAN_GLOBAL:
            # Flip the final order direction
            direction = "sell" if original_direction == "buy" else "buy"

        entry = book.best_ask if direction == "buy" else book.best_bid
        max_lev = self.simulator.leverage_limits.get(symbol, 125)

        # Dynamic TP/SL calculation
        entry_fee_rate = MAKER_FEE if ENTRY_ORDER_TYPE == "limit" else TAKER_FEE
        tp_exit_fee_rate = MAKER_FEE if TP_ORDER_TYPE == "limit" else TAKER_FEE
        sl_exit_fee_rate = MAKER_FEE if SL_ORDER_TYPE == "limit" else TAKER_FEE

        # Leverage and Fee rates for RRR synchronization
        max_lev = self.simulator.leverage_limits.get(symbol, 20)
        entry_fee_rate = MAKER_FEE if ENTRY_ORDER_TYPE == "limit" else TAKER_FEE
        tp_exit_fee_rate = MAKER_FEE if TP_ORDER_TYPE == "limit" else TAKER_FEE
        sl_exit_fee_rate = MAKER_FEE if SL_ORDER_TYPE == "limit" else TAKER_FEE

        # 1. Calculate Base SL_MOVE (Volatility-aware or config fallback)
        if USE_ATR_SL and features.get("atr"):
            sl_move = (features["atr"] * ATR_SL_MULT) / entry
        else:
            sl_move = SL_MOVE

        sl_move = max(sl_move, 0.001)

        # 2. Synchronize TP_MOVE to maintain the 1:2 Net RRR
        # To secure the RRR, Net_TP must be 2x Net_SL.
        # Net_TP = (tp_move - entry_fee - tp_exit_fee - slippage)
        # Net_SL = (sl_move + entry_fee + sl_exit_fee)  <- Total lost on stop
        net_sl_cost = sl_move + entry_fee_rate + sl_exit_fee_rate

        # Calculate target TP_MOVE based on desired ROE vs current SL cost
        tp_move_from_roe = (TARGET_NET_ROE / max_lev) + entry_fee_rate + tp_exit_fee_rate + EXPECTED_SLIPPAGE

        # Use the larger of (2x SL) or (Target ROE) to ensure we don't compress RRR
        tp_move = max(tp_move_from_roe, (net_sl_cost * 2) + entry_fee_rate + tp_exit_fee_rate + EXPECTED_SLIPPAGE)

        # 3. Apply TP Relaxation if needed (reduces RRR to 1.5:1 if flat)
        if USE_TP_RELAXATION:
            drt_offset = abs(features.get("drt", 0.5) - 0.5)
            if drt_offset < TP_RELAXATION_THRESHOLD:
                tp_move = (net_sl_cost * 1.5) + entry_fee_rate + tp_exit_fee_rate + EXPECTED_SLIPPAGE
                log.debug(f"TP RELAXED for {symbol}: using 1.5:1 RRR (Target Net ROE: {RELAXED_ROE_TARGET*100:.1f}%) due to flat DRT ({drt_offset:.4f})")

        # 4. Final Caps and Floors
        if USE_ATR_CAPPED_TP and features.get("atr"):
            atr_15m_move = (features["atr"] * 3.8) / entry
            tp_move = min(tp_move, atr_15m_move)

        tp_move = max(tp_move, TP_MOVE)

        # 5. Final SL Recalibration: If TP_MOVE was capped or floored, we MUST adjust SL to keep RRR
        net_tp_win = tp_move - entry_fee_rate - tp_exit_fee_rate - EXPECTED_SLIPPAGE
        sl_move = (net_tp_win / 2) - entry_fee_rate - sl_exit_fee_rate
        sl_move = max(sl_move, 0.001)

        if direction == "buy":
            exit_price = entry * (1 + tp_move)
            stop_price = entry * (1 - sl_move)
        else:
            exit_price = entry * (1 - tp_move)
            stop_price = entry * (1 + sl_move)

        # Re-check distances to ensure WEIGHTS are preserved in Contrarian flip
        # If we flipped a LONG (Entry +0.6% TP, Entry -0.4% SL) to a SHORT,
        # it must become (Entry -0.6% TP, Entry +0.4% SL).
        # The current math above already handles this because it uses (1 + tp) for buy
        # and (1 - tp) for sell.

        # --- VOL-ADJUSTED RISK LOGIC ---
        risk_fraction = RISK_PER_TRADE
        if USE_VOL_ADJUSTED_RISK:
            atr_pct = features.get("atr", 0) / entry if entry > 0 else 0
            if atr_pct > ATR_VOL_THRESHOLD:
                risk_fraction = RISK_PER_TRADE * REDUCED_RISK_FRACTION
                log.debug(f"RISK REDUCED for {symbol}: ATR {atr_pct:.4f} > {ATR_VOL_THRESHOLD}")

        risk_amount = equity * risk_fraction

        # Fee-aware sizing: subtract expected round-trip fees from the per-unit risk capacity
        if FEE_AWARE_SIZING:
            entry_fee_rate = MAKER_FEE if ENTRY_ORDER_TYPE == "limit" else TAKER_FEE
            exit_fee_rate = TAKER_FEE # Worst case for SL
            fee_per_unit = entry * (entry_fee_rate + exit_fee_rate)
            risk_per_unit = abs(entry - stop_price) + fee_per_unit
        else:
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

        # Multi-Stage TP Calculation
        tp1_price = None
        tp1_qty = 0
        tp2_qty = qty
        if USE_BREAKEVEN_TRIGGER and EXIT_STRATEGY == "BE+TP1+TP2":
            # Estimate BE price to calculate TP1 distance
            # be_move = (entry_fee_rate + MAKER_FEE) + (BREAKEVEN_PROFIT_BUFFER / max_lev)
            be_move = (entry_fee_rate + MAKER_FEE) + (BREAKEVEN_PROFIT_BUFFER / max_lev)
            if direction == "buy":
                be_price = entry * (1 + be_move)
                distance = exit_price - be_price
                tp1_price = be_price + (distance * TP1_BUFFER_PCT)
            else:
                be_price = entry * (1 - be_move)
                distance = be_price - exit_price
                tp1_price = be_price - (distance * TP1_BUFFER_PCT)

            tp1_price = round(tp1_price, price_place)
            tp1_qty = math.floor(qty * TP1_QTY_RATIO * (10 ** vol_place)) / (10 ** vol_place)
            tp2_qty = round(qty - tp1_qty, vol_place)

        # Final leverage check
        max_lev = self.simulator.leverage_limits.get(symbol, 20)
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
            "is_contrarian": CONTRARIAN_GLOBAL
        }

        # Tag Premium/Discount for analysis
        drt_fast = features.get("drt_fast", 0.5)
        drt_slow = features.get("drt_slow", 0.5)

        premium_fast = "PREM" if drt_fast > 0.5 else "DISC"
        premium_slow = "PREM" if drt_slow > 0.5 else "DISC"

        # Include all features and patterns in the signal for recording
        signal.update(features)

        # Override with formatted values for logging if needed
        signal.update({
            "rsi": rsi,
            "drt_f": f"{drt_fast:.4f}({premium_fast})",
            "drt_s": f"{drt_slow:.4f}({premium_slow})",
        })
        return signal

class DummyModel:
    def predict(self, symbol, book, equity=None):
        return None
