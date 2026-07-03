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

    def get_state(self, key: str, simulator=None) -> Optional[str]:
        if simulator and hasattr(simulator, "db") and simulator.db:
            return simulator.db.get_strategy_state(self.file_name, key)
        return None
