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

    def get_config(self, key: str, default: Any = None) -> Any:
        return getattr(config, key, default)

    def save_state(self, key: str, value: Any, simulator=None):
        if simulator and hasattr(simulator, "db") and simulator.db:
            simulator.db.save_strategy_state(self.file_name, key, value)
        else:
            self._mem_state[key] = str(value)

    def get_state(self, key: str, simulator=None) -> Optional[str]:
        if simulator and hasattr(simulator, "db") and simulator.db:
            return simulator.db.get_strategy_state(self.file_name, key)
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

        # Sort milestones by the count of occurrences
        sorted_m = sorted(self.milestones.items(), key=lambda x: len(x[1]), reverse=True)

        lines = []
        for k, occurrences in sorted_m:
            count = len(occurrences)

            time_parts = []
            # If many occurrences, show a selection
            display_occ = occurrences if count <= 3 else occurrences[:2] + [{"sep": "..."}] + occurrences[-1:]

            for occ in display_occ:
                if "sep" in occ:
                    time_parts.append("...")
                    continue

                ts = occ["ts"]
                tf = occ["tf"]
                dt_open = convert_to_local(ts)
                open_str = dt_open.strftime("%m-%d %H:%M")

                if tf in tf_map:
                    dt_close = convert_to_local(ts + tf_map[tf] - 1)
                    time_parts.append(f"{open_str}-{dt_close.strftime('%H:%M')} ({tf})")
                else:
                    time_parts.append(f"{open_str} ({tf})")

            time_str = ", ".join(time_parts)
            lines.append(f"  - {k:30}: {count:<4} | {time_str}")

        return "\n".join(lines)
