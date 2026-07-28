"""
1. Summary: Specialized risk management and trading eligibility gatekeeper.
2. Description: Evaluates drawdown boundaries, return target ceilings, trade count limits, and active position durations. Controls asset eligibility via liquidity thresholds, cooldown clocks, and correlation constraints.
3. Context: Promotes defensive execution and provides central safeguards protecting aggregate account equity.
"""
import time
import logging
from typing import Dict, Any

log = logging.getLogger("scalper.engine.risk")

class RiskGate:
    def __init__(self, config):
        self.config = config
        self.last_exit_time: Dict[str, float] = {}

    def check_limits(self, equity: float, starting_equity: float, peak_equity: float, total_trades: int, elapsed_time: float) -> bool:
        """
        Returns True if limits are exceeded and trading should stop.
        """
        # 1. Drawdown Limit
        if peak_equity > 0 and equity <= self.config.DRAWDOWN_LIMIT * peak_equity:
            log.critical(f"DRAWDOWN LIMIT HIT: equity={equity:.2f}, peak={peak_equity:.2f}")
            return True

        # 2. ROI Limit
        roi = (equity / starting_equity) - 1
        if roi >= self.config.TOTAL_ROI_LIMIT:
            log.critical(f"ROI TARGET REACHED: equity={equity:.2f}, ROI={roi*100:.1f}%")
            return True

        # 3. Trade Count Limit
        if total_trades >= self.config.MAX_TRADES_LIMIT:
            log.critical(f"TRADE LIMIT REACHED: {total_trades} trades")
            return True

        # 4. Duration Limit
        if elapsed_time >= self.config.MAX_DURATION:
            log.critical(f"DURATION LIMIT REACHED: {elapsed_time:.0f}s")
            return True

        return False

    def is_asset_tradable(self, symbol: str, side: str, equity: float, open_positions: dict, pending_entries: set, leverage_limits: dict, exchange=None, books=None, features: dict = None, signal: dict = None, get_current_time_func=None, strategies_count: int = 1) -> bool:
        """
        Gates asset entries based on liquidity, correlation, cooldown, and aggregate margin limits.
        """
        if signal and signal.get("bypass_global_filters"):
            return True

        # P0-3: Position duplicate/bookkeeping checks
        pos_key = f"{symbol}_{side}"
        if pos_key in open_positions or pos_key in pending_entries:
            return False

        # P0-4: Check aggregate margin exposure cap (default 10% of equity)
        total_open_margin = sum(pos.get("margin", 0.0) for pos in open_positions.values())
        max_margin = equity * getattr(self.config, "MAX_AGGREGATE_MARGIN_PCT", 0.10)
        if total_open_margin >= max_margin:
            return False

        # Correlation check
        if exchange and hasattr(exchange, "asset_correlations"):
            corrs = exchange.asset_correlations.get(symbol, {})
            for other_sym, score in corrs.items():
                if score > 0.9:
                    if f"{other_sym}_buy" in open_positions or f"{other_sym}_sell" in open_positions:
                         from ta.patterns.spread import detect_divergence
                         h1 = exchange.ohlcv.get(symbol, {}).get("1m", [])
                         h2 = exchange.ohlcv.get(other_sym, {}).get("1m", [])
                         div = detect_divergence(h1, h2, score)

                         if div.get('divergence_active') and div['recommended_side'] == side:
                             log.debug(f"STAT-ARB | Overriding correlation block for {symbol} {side}: Z={div['z_score']:.2f}")
                             continue

                         return False

        # Check volume/liquidity
        if books and symbol in books:
            book = books[symbol]
            bid_vol, ask_vol = book.top_bid_ask_qty()
            if getattr(self.config, "RESTRICT_LIQUIDITY", False) and (bid_vol < 1 or ask_vol < 1):
                return False

        if strategies_count <= 1:
            other_side = "sell" if side == "buy" else "buy"
            other_key = f"{symbol}_{other_side}"
            if other_key in open_positions or other_key in pending_entries:
                return False

        # Cooldown check
        last_exit = self.last_exit_time.get(symbol, 0)
        cooldown = getattr(self.config, "REENTRY_COOLDOWN", 60.0)
        if features and features.get("atr") and features.get("mid"):
            atr_pct = features["atr"] / features["mid"]
            scale_factor = max(0.2, min(3.0, 0.001 / (atr_pct + 1e-9)))
            cooldown *= scale_factor

        current_time = get_current_time_func(symbol) if get_current_time_func else time.time()
        if current_time - last_exit < cooldown:
            return False

        return True
