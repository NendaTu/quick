import math
import logging

log = logging.getLogger("scalper.ta.scoring")

class ScoringEngine:
    """
    Stateless Unified Scoring Engine.
    Converts 18 technical indicators into raw directional scores (-100 to +100),
    applies user-defined static weights & dynamic learning multipliers, and
    aggregates them using normal weighted average.
    """

    @staticmethod
    def _linear_map(val: float, min_val: float, max_val: float, min_score: float, max_score: float) -> float:
        """
        Helper to map a continuous value to a score range linearly, with clamping.
        """
        if val is None:
            return 0.0
        if max_val == min_val:
            return min_score
        frac = (val - min_val) / (max_val - min_val)
        score = min_score + frac * (max_score - min_score)
        low = min(min_score, max_score)
        high = max(min_score, max_score)
        return max(low, min(high, score))

    def evaluate(self, features: dict, side: str, config_context, dynamic_weights: dict = None, overrides: dict = None) -> dict:
        """
        Evaluates features and returns raw scores, weighted scores, aggregate score, decision, and reasons.

        :param features: Dict of indicator features from get_features()
        :param side: Evaluation target trade direction ('buy' or 'sell')
        :param config_context: Configuration context containing weights and thresholds
        :param dynamic_weights: Optional adaptive learning weights dictionary from LearningModel
        :param overrides: Optional dict of overrides for specific strategies: e.g. {"rsi": {"weight": 0.0}}
        """
        side_sign = 1.0 if side == "buy" else -1.0
        contrarian_filter = getattr(config_context, 'CONTRARIAN_FILTER', False)
        filter_multiplier = -1.0 if contrarian_filter else 1.0

        raw_scores = {}
        weighted_scores = {}

        # Default configuration values
        btc_mom_thresh = getattr(config_context, 'BTC_MOMENTUM_THRESHOLD', 0.001)
        trend_15m_min = getattr(config_context, 'TREND_15M_MIN', 0.0001)
        btc_conf_15m_min = getattr(config_context, 'BTC_CONF_15M_MIN', 0.0002)
        btc_conf_1h_min = getattr(config_context, 'BTC_CONF_1H_MIN', 0.0002)
        min_volatility = getattr(config_context, 'MIN_VOLATILITY', 0.0) or 0.0001
        max_spread_pct = getattr(config_context, 'MAX_SPREAD_PCT', 0.002)
        vol_pct_min = getattr(config_context, 'VOL_PCT_MIN', 0.01) or 0.01
        min_confidence = getattr(config_context, 'MIN_CONFIDENCE', 0.66)

        # ----------------- 1. DIRECTIONAL INDICATORS (-100 to +100) -----------------
        # 1.1 RSI
        rsi = features.get("rsi", 50.0) if features.get("rsi") is not None else 50.0
        raw_scores["rsi"] = self._linear_map(rsi, 0.0, 100.0, -100.0, 100.0) * filter_multiplier

        # 1.2 RSI Short Ceiling Trend Protection
        adx = features.get("adx", 0.0) if features.get("adx") is not None else 0.0
        if rsi > 85.0 and adx > 25.0:
            raw_scores["rsi_ceiling"] = 100.0 * filter_multiplier
        else:
            raw_scores["rsi_ceiling"] = 0.0

        # 1.3 Order Book Imbalance
        imbalance = features.get("imbalance", 0.0) if features.get("imbalance") is not None else 0.0
        raw_scores["imbalance"] = imbalance * 100.0 * filter_multiplier

        # 1.4 MACD Histogram
        macd_hist = features.get("macd_hist", 0.0) if features.get("macd_hist") is not None else 0.0
        atr = features.get("atr", 0.0) if features.get("atr") is not None else 0.0
        normalized_macd = macd_hist / (atr * 0.1) if atr > 0.0 else macd_hist
        raw_scores["macd"] = self._linear_map(normalized_macd, -1.0, 1.0, -100.0, 100.0) * filter_multiplier

        # 1.5 15M Trend Price Slope
        asset_15m = features.get("asset_15m", 0.0) if features.get("asset_15m") is not None else 0.0
        raw_scores["trend_15m"] = self._linear_map(asset_15m, -trend_15m_min, trend_15m_min, -100.0, 100.0) * filter_multiplier

        # 1.6 Asset Confluence
        raw_scores["asset_conf"] = raw_scores["trend_15m"]

        # 1.7 Supertrend
        supertrend_dir = features.get("supertrend_dir", 0) if features.get("supertrend_dir") is not None else 0
        raw_scores["supertrend"] = float(supertrend_dir) * 100.0 * filter_multiplier

        # 1.8 DRT Trend
        drt = features.get("drt", 0.5) if features.get("drt") is not None else 0.5
        raw_scores["drt"] = (drt - 0.5) * 200.0 * filter_multiplier

        # 1.9 Directional Sanity (Agreement between DRT and predicted side)
        # If DRT is bullish (>0.5), scores positive bias (+100). If bearish, scores negative bias (-100).
        if drt > 0.5:
            raw_scores["sanity"] = 100.0 * filter_multiplier
        elif drt < 0.5:
            raw_scores["sanity"] = -100.0 * filter_multiplier
        else:
            raw_scores["sanity"] = 0.0

        # 1.10 BTC Momentum
        btc_15m = features.get("btc_15m", 0.0) if features.get("btc_15m") is not None else 0.0
        raw_scores["btc_mom"] = self._linear_map(btc_15m, -btc_mom_thresh, btc_mom_thresh, -100.0, 100.0) * filter_multiplier

        # 1.11 BTC Confluence (MTF alignment rates)
        btc_1h = features.get("btc_1h", 0.0) if features.get("btc_1h") is not None else 0.0
        btc_4h = features.get("btc_4H", features.get("btc_4h", 0.0))
        btc_4h = btc_4h if btc_4h is not None else 0.0
        btc_1d = features.get("btc_1D", features.get("btc_1d", 0.0))
        btc_1d = btc_1d if btc_1d is not None else 0.0

        s_15m = self._linear_map(btc_15m, -btc_conf_15m_min, btc_conf_15m_min, -25.0, 25.0)
        s_1h = self._linear_map(btc_1h, -btc_conf_1h_min, btc_conf_1h_min, -25.0, 25.0)
        s_4h = self._linear_map(btc_4h, -0.0002, 0.0002, -25.0, 25.0)
        s_1d = self._linear_map(btc_1d, -0.0002, 0.0002, -25.0, 25.0)
        raw_scores["btc_conf"] = (s_15m + s_1h + s_4h + s_1d) * filter_multiplier

        # 1.12 Higher Timeframe Trend Bias (Bullish, Bearish, Neutral)
        bias = features.get("bias", "neutral")
        if bias == "bullish":
            raw_scores["htf_bias"] = 100.0 * filter_multiplier
        elif bias == "bearish":
            raw_scores["htf_bias"] = -100.0 * filter_multiplier
        else:
            raw_scores["htf_bias"] = 0.0

        # 1.13 Market Structure Breaks (BOS / MSS)
        struct = features.get("structure_signal")
        if struct and isinstance(struct, str):
            struct_lower = struct.lower()
            if "bullish" in struct_lower:
                raw_scores["structure"] = 100.0 if "bos" in struct_lower else 50.0
            elif "bearish" in struct_lower:
                raw_scores["structure"] = -100.0 if "bos" in struct_lower else -50.0
            else:
                raw_scores["structure"] = 0.0
        else:
            raw_scores["structure"] = 0.0
        raw_scores["structure"] *= filter_multiplier

        # ----------------- 2. QUALITY / NON-DIRECTIONAL INDICATORS -----------------
        # Mapped as side_sign * quality_penalty (where penalty goes from -100 to 0)
        # 2.1 Volume Influx / Spike
        vol_influx = features.get("volume_influx", False)
        vol_spike = features.get("volume_spike", False)
        if vol_influx and vol_spike:
            qp_influx = 0.0
        elif vol_influx or vol_spike:
            qp_influx = -30.0
        else:
            qp_influx = -100.0
        raw_scores["vol_influx"] = side_sign * qp_influx

        # 2.2 ATR Volatility Floor
        if atr >= min_volatility:
            qp_atr = 0.0
        else:
            qp_atr = self._linear_map(atr, 0.0, min_volatility, -100.0, 0.0)
        raw_scores["atr"] = side_sign * qp_atr

        # 2.3 Spread safety
        mid = features.get("mid", 0.0) if features.get("mid") is not None else 0.0
        spread_pct = features.get("spread_pct", 0.0)
        if spread_pct is None or spread_pct == 0.0:
            # Fallback calculation if not in features
            best_bid = features.get("best_bid", mid)
            best_ask = features.get("best_ask", mid)
            if best_bid and best_ask and mid > 0.0:
                spread_pct = (best_ask - best_bid) / mid
            else:
                spread_pct = 0.0

        if spread_pct <= max_spread_pct:
            qp_spread = 0.0
        else:
            qp_spread = self._linear_map(spread_pct, max_spread_pct, max_spread_pct * 2.0, 0.0, -100.0)
        raw_scores["spread"] = side_sign * qp_spread

        # 2.4 Order Book Volume depth
        vol_pct = features.get("vol_pct", 0.0) if features.get("vol_pct") is not None else 0.0
        if vol_pct >= vol_pct_min:
            qp_vol_pct = 0.0
        else:
            qp_vol_pct = self._linear_map(vol_pct, 0.0, vol_pct_min, -100.0, 0.0)
        raw_scores["vol_pct"] = side_sign * qp_vol_pct

        # 2.5 Model Confidence
        confidence = features.get("confidence", 1.0) if features.get("confidence") is not None else 1.0
        if confidence >= min_confidence:
            qp_conf = 0.0
        else:
            qp_conf = self._linear_map(confidence, 0.0, min_confidence, -100.0, 0.0)
        raw_scores["confidence"] = side_sign * qp_conf

        # ----------------- 3. WEIGHT MULTIPLICATION & AGGREGATION -----------------
        # Separate directional and non-directional keys to avoid denominator dilution [REPAIR]
        directional_keys = ["rsi", "rsi_ceiling", "imbalance", "macd", "trend_15m", "asset_conf", "supertrend", "drt", "sanity", "btc_mom", "btc_conf", "htf_bias", "structure"]
        non_directional_keys = ["vol_influx", "atr", "spread", "vol_pct", "confidence"]

        total_weighted_score = 0.0
        total_weight = 0.0

        # 3.1 Calculate directional indicator average
        for key in directional_keys:
            raw_val = raw_scores.get(key, 0.0)
            static_weight_key = f"WEIGHT_{key.upper()}"
            static_weight = getattr(config_context, static_weight_key, 1.0)

            if overrides and key in overrides:
                if "weight" in overrides[key]:
                    static_weight = overrides[key]["weight"]

            dynamic_factor = 1.0
            if dynamic_weights and key in dynamic_weights:
                dynamic_factor = dynamic_weights[key]

            final_weight = static_weight * dynamic_factor
            weighted_val = raw_val * final_weight
            weighted_scores[key] = weighted_val

            if final_weight > 0.0:
                total_weighted_score += weighted_val
                total_weight += final_weight

        aggregated_score = total_weighted_score / total_weight if total_weight > 0.0 else 0.0

        # 3.2 Calculate and apply non-directional quality penalties directly to avoid denominator dilution
        penalty_sum = 0.0
        for key in non_directional_keys:
            raw_val = raw_scores.get(key, 0.0)
            static_weight_key = f"WEIGHT_{key.upper()}"
            static_weight = getattr(config_context, static_weight_key, 1.0)

            if overrides and key in overrides:
                if "weight" in overrides[key]:
                    static_weight = overrides[key]["weight"]

            dynamic_factor = 1.0
            if dynamic_weights and key in dynamic_weights:
                dynamic_factor = dynamic_weights[key]

            final_weight = static_weight * dynamic_factor
            weighted_val = raw_val * final_weight
            weighted_scores[key] = weighted_val

            if final_weight > 0.0:
                penalty_sum += weighted_val

        aggregated_score += penalty_sum

        # Determine decision & reason
        entry_threshold = getattr(config_context, 'ENTRY_SCORE_THRESHOLD', 30.0)
        report_only = getattr(config_context, 'BY_DEFAULT_REPORT_ONLY', True)

        # Direction checks
        passed_threshold = False
        if side == "buy" and aggregated_score >= entry_threshold:
            passed_threshold = True
        elif side == "sell" and aggregated_score <= -entry_threshold:
            passed_threshold = True

        if passed_threshold:
            decision = "TAKEN"
            reason = f"Aggregated score {aggregated_score:.2f} passed threshold {entry_threshold:.2f} for side {side}."
        else:
            if report_only:
                decision = "REPORT_ONLY"
            else:
                decision = "REJECTED"
            reason = f"Aggregated score {aggregated_score:.2f} failed threshold {entry_threshold:.2f} for side {side}."

        return {
            "side": side,
            "raw_scores": raw_scores,
            "weighted_scores": weighted_scores,
            "aggregated_score": aggregated_score,
            "entry_threshold": entry_threshold,
            "decision": decision,
            "reason": reason
        }
