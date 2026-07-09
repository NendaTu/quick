import logging
from typing import Dict, Optional, Any
from engine.base import BaseStrategy
import config

class JBaseStrategy(BaseStrategy):
    """
    Enhanced Base Strategy for the Jules platform.
    Adds support for config overrides and shared helper methods.
    """
    def __init__(self, name: str, version: str, author: str, config_overrides: Optional[Dict] = None):
        super().__init__(config_overrides)
        self.name = name
        self.version = version
        self.author = author
        self.strategy_id = name # Default to name, to be overriden by loader
        self.logger = logging.getLogger(f"strategies.{name}")
        self.file_name = f"{name}.{version}.{author}.py"
        self._mem_state = {} # In-memory fallback
        self.milestones = {} # Event tracking
        self._last_milestone_ts = {} # Prevent double-counting in the same bar

        # Apply config overrides
        for key, value in self.config_overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)

    def log_strategy_info(self):
        print(f"Strategy: {self.name} v{self.version} by {self.author}")
        print(f"Description: {self.__doc__}")

    def is_ready(self, symbol: str) -> bool:
        """
        [TECH-001] Checks if the strategy has enough historical data for authenticity.
        Returns True if all required history buckets are filled.
        """
        if not hasattr(self, "required_history"):
            return True # Legacy / Simple strategies are always ready

        for tf, count in self.required_history.items():
            h = self._get_ohlcv(symbol, tf)
            if len(h) < count:
                return False
        return True

    def get_readiness_eta(self, symbol: str) -> str:
        """[TECH-001] Estimates wait time for warmup."""
        if self.is_ready(symbol): return "READY"

        tf_map = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400, "1D": 86400}
        max_eta = 0
        status = []

        for tf, count in self.required_history.items():
            h = self._get_ohlcv(symbol, tf)
            missing = count - len(h)
            if missing > 0:
                eta = missing * tf_map.get(tf, 60)
                max_eta = max(max_eta, eta)
                status.append(f"{missing} {tf}")

        return f"Warming up (Need {', '.join(status)}) | ETA: {int(max_eta)}s"

    def _get_ohlcv(self, symbol: str, tf: str):
        # Default implementation, to be overriden or used via self.simulator
        if hasattr(self, "simulator") and self.simulator:
            return self.simulator.ohlcv.get(symbol, {}).get(tf, [])
        return []

    def get_config(self, key: str, default: Any = None) -> Any:
        return getattr(config, key, default)

    def save_state(self, key: str, value: Any, simulator=None):
        if simulator and hasattr(simulator, "db") and simulator.db:
            simulator.db.save_strategy_state(self.strategy_id, key, value)
        else:
            self._mem_state[key] = str(value)

    def get_state(self, key: str, simulator=None) -> Optional[str]:
        if simulator and hasattr(simulator, "db") and simulator.db:
            return simulator.db.get_strategy_state(self.strategy_id, key)
        return self._mem_state.get(key)

    def record_milestone(self, key: str, timestamp: float = 0, timeframe: str = ""):
        """Records a strategy milestone with its timestamp and timeframe."""
        if key not in self.milestones:
            self.milestones[key] = []

        # Prevent duplicate recording for the exact same candle
        if any(m["ts"] == timestamp and m["tf"] == timeframe for m in self.milestones[key]):
            return False

        self.milestones[key].append({"ts": timestamp, "tf": timeframe})
        return True

    def get_milestone_report(self) -> str:
        if not self.milestones:
            return ""

        from ta.utils import convert_to_local
        tf_map = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400, "1D": 86400}

        # Define the logical order of milestones for the funnel
        milestone_order = [
            "Phase 0:", "Phase 1:", "Phase 2:", "Phase 3:",
            "Phase 4:", "Phase 5:", "Phase 6:", "Phase 7:"
        ]

        def get_order(key):
            for i, prefix in enumerate(milestone_order):
                if key.startswith(prefix): return i
            return 999

        sorted_m = sorted(self.milestones.items(), key=lambda x: get_order(x[0]))

        lines = []
        for k, occurrences in sorted_m:
            count = len(occurrences)
            first = occurrences[0]
            last = occurrences[-1]

            def fmt_occ(occ):
                dt = convert_to_local(occ["ts"])
                time_str = dt.strftime("%m-%d %H:%M")
                if occ["tf"] in tf_map:
                    dt_close = convert_to_local(occ["ts"] + tf_map[occ["tf"]] - 1)
                    return f"{time_str}-{dt_close.strftime('%H:%M')} ({occ['tf']})"
                return f"{time_str} ({occ['tf']})"

            if count == 1:
                occ_str = fmt_occ(first)
            else:
                occ_str = f"First: {fmt_occ(first)} | Last: {fmt_occ(last)}"

            lines.append(f"  - {k:30}: {count:<4} | {occ_str}")

        return "\n".join(lines)
