"""
1. Summary: Single-concern bookkeeping ledger for open and pending positions.
2. Description: Manages thread-safe local dictionaries and set definitions tracking currently active open positions and pending entries dispatched to exchanges.
3. Context: Used by core execution loops to determine tradability and update position histories.
"""
from typing import Dict, Set, Any, Optional

class PositionLedger:
    def __init__(self):
        # Open positions map: key is 'SYMBOL_side'
        self.open_positions: Dict[str, dict] = {}
        # Pending entries: key is 'SYMBOL_side'
        self.pending_entries: Set[str] = set()

    def add_position(self, pos_key: str, position_details: dict):
        self.open_positions[pos_key] = position_details

    def get_position(self, pos_key: str) -> Optional[dict]:
        return self.open_positions.get(pos_key)

    def remove_position(self, pos_key: str) -> Optional[dict]:
        return self.open_positions.pop(pos_key, None)

    def add_pending(self, pos_key: str):
        self.pending_entries.add(pos_key)

    def remove_pending(self, pos_key: str):
        if pos_key in self.pending_entries:
            self.pending_entries.remove(pos_key)

    def is_open(self, pos_key: str) -> bool:
        """Checks if a position is open (R1-1)."""
        return pos_key in self.open_positions

    def is_pending(self, pos_key: str) -> bool:
        """Checks if a position is pending (R1-1)."""
        return pos_key in self.pending_entries

    def get_open_keys(self) -> list:
        """Returns a list of open position keys (R1-1)."""
        return list(self.open_positions.keys())

    def get_pending_keys(self) -> list:
        """Returns a list of pending entry keys (R1-1)."""
        return list(self.pending_entries)

    def get_all_positions(self) -> Dict[str, dict]:
        """Returns a copy of all open positions (R1-1)."""
        return self.open_positions.copy()

    def clear(self):
        self.open_positions.clear()
        self.pending_entries.clear()

    @property
    def position_count(self) -> int:
        return len(self.open_positions)

    @property
    def pending_count(self) -> int:
        return len(self.pending_entries)
