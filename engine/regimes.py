"""
1. Summary: Specialized classifier categorizing assets by volatility regime.
2. Description: Analyzes historical closed hourly candles and rolling ATR boundaries to segment assets into majors, high-beta, and stable regimes.
3. Context: Promotes modular segregation of asset categorization from gating check mechanisms.
"""
import logging
from typing import Dict

log = logging.getLogger("scalper.engine.regimes")

class RegimeClassifier:
    def __init__(self):
        self.asset_regimes: Dict[str, str] = {}

    def classify_asset_regimes(self, symbol: str = None, exchange=None, enabled_assets=None):
        """
        Classifies asset regimes based on ATR volatility ratios.
        """
        targets = [symbol] if symbol else (enabled_assets or [])
        if not exchange:
            return

        for sym in targets:
            h = exchange.ohlcv.get(sym, {}).get("1H", [])
            if not h:
                self.asset_regimes[sym] = 'major'
                continue

            closes = [c['c'] for c in h]
            highs = [c['h'] for c in h]
            lows = [c['l'] for c in h]

            from ta.indicators.atr import compute_atr
            atr = compute_atr(highs, lows, closes, period=20)
            price = closes[-1]
            atr_pct = (atr / price) if price > 0 else 0

            if sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
                self.asset_regimes[sym] = 'major'
            elif atr_pct > 0.005:
                self.asset_regimes[sym] = 'high_beta'
            else:
                self.asset_regimes[sym] = 'stable'

        if not symbol:
            counts = {r: list(self.asset_regimes.values()).count(r) for r in ['major', 'high_beta', 'stable']}
            log.info(f"REGIMES | Classification Complete: {counts}")
