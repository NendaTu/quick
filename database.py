# database.py

import sqlite3
import time
import logging
import threading
import queue
from typing import Dict

log = logging.getLogger("scalper.database")

class Database:
    def __init__(self, db_path=None):
        # [TECH-001] Ensure absolute pathing for the database to prevent fragmentation
        # when running from different script locations.
        if db_path is None:
            import os
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.db_path = os.path.join(base_dir, "market_data.db")
        else:
            self.db_path = db_path

        self._conn = None
        self._init_db()
        self.write_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread = threading.Thread(target=self._write_worker, daemon=True)
        self.worker_thread.start()

    @property
    def connection(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, timeout=30)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self):
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ticks (
                    symbol TEXT,
                    timestamp REAL,
                    price REAL,
                    side TEXT,
                    size REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    symbol TEXT,
                    timeframe TEXT,
                    timestamp REAL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    session_id INTEGER,
                    timestamp REAL,
                    level TEXT,
                    logger TEXT,
                    message TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS discovered_assets (
                    timestamp REAL,
                    assets TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    session_id INTEGER,
                    timestamp REAL,
                    symbol TEXT,
                    side TEXT,
                    price REAL,
                    data TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_weights (
                    indicator TEXT PRIMARY KEY,
                    weight REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategy_state (
                    strategy_id TEXT,
                    key TEXT,
                    value TEXT,
                    PRIMARY KEY (strategy_id, key)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    strategy_id TEXT,
                    symbol TEXT,
                    side TEXT,
                    entry_ts REAL,
                    entry_price REAL,
                    qty REAL,
                    exit_ts REAL,
                    exit_price REAL,
                    pnl REAL,
                    exit_type TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks (symbol, timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candles_symbol_tf_time ON candles (symbol, timeframe, timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_session ON logs (session_id)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS asset_metadata (
                    symbol TEXT,
                    timeframe TEXT,
                    earliest_ts REAL,
                    is_exhausted INTEGER,
                    PRIMARY KEY (symbol, timeframe)
                )
            """)

            # Create a new session
            cursor = conn.execute("INSERT INTO sessions (start_time) VALUES (?)", (time.time(),))
            self.session_id = cursor.lastrowid
            conn.commit()

    def _write_worker(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout=10000")
        while not self.stop_event.is_set():
            try:
                # Batch processing
                items = []
                try:
                    # Wait for first item
                    items.append(self.write_queue.get(timeout=0.5))
                    # Try to grab more for batching
                    for _ in range(1000):
                        items.append(self.write_queue.get_nowait())
                except (queue.Empty):
                    pass

                if not items:
                    continue

                cursor = conn.cursor()
                for type, data in items:
                    if type == "metadata":
                        cursor.execute("""
                            INSERT OR REPLACE INTO asset_metadata (symbol, timeframe, earliest_ts, is_exhausted)
                            VALUES (?, ?, ?, ?)
                        """, data)
                    if type == "tick":
                        cursor.execute(
                            "INSERT INTO ticks (symbol, timestamp, price, side, size) VALUES (?, ?, ?, ?, ?)",
                            data
                        )
                    elif type == "candle":
                        cursor.execute("""
                            INSERT OR REPLACE INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, data)
                    elif type == "log":
                        cursor.execute(
                            "INSERT INTO logs (session_id, timestamp, level, logger, message) VALUES (?, ?, ?, ?, ?)",
                            data
                        )
                    elif type == "signal":
                        cursor.execute(
                            "INSERT INTO signals (session_id, timestamp, symbol, side, price, data) VALUES (?, ?, ?, ?, ?, ?)",
                            data
                        )
                    elif type == "purge":
                        tick_retention_seconds, candle_retention_days = data
                        now = time.time()
                        res_ticks = cursor.execute("DELETE FROM ticks WHERE timestamp < ?", (now - tick_retention_seconds,))
                        res_candles = cursor.execute("DELETE FROM candles WHERE timestamp < ?", (now - candle_retention_days * 86400,))
                        log.info(f"Background Purge: {res_ticks.rowcount} ticks, {res_candles.rowcount} candles.")
                    elif type == "purge_sessions":
                        keep_sessions = data
                        cursor.execute("SELECT id FROM sessions ORDER BY start_time DESC LIMIT ?", (keep_sessions,))
                        recent_ids = [row[0] for row in cursor.fetchall()]
                        if recent_ids:
                            placeholders = ",".join("?" * len(recent_ids))
                            cursor.execute(f"DELETE FROM logs WHERE session_id NOT IN ({placeholders})", recent_ids)
                            cursor.execute(f"DELETE FROM sessions WHERE id NOT IN ({placeholders})", recent_ids)
                            log.info(f"Background Purge Sessions: Kept IDs {recent_ids}")
                    elif type == "trade":
                        cursor.execute("""
                            INSERT INTO trades (session_id, strategy_id, symbol, side, entry_ts, entry_price, qty, exit_ts, exit_price, pnl, exit_type)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, data)
                conn.commit()
                for _ in range(len(items)):
                    self.write_queue.task_done()
            except Exception as e:
                log.error(f"DB Write Error: {e}")
                time.sleep(1)
        conn.close()

    def save_tick(self, symbol, timestamp, price, side, size):
        self.write_queue.put(("tick", (symbol, timestamp, price, side, size)))

    def save_candle(self, symbol, timeframe, timestamp, open, high, low, close, volume):
        self.write_queue.put(("candle", (symbol, timeframe, timestamp, open, high, low, close, volume)))

    def save_log(self, level, logger_name, message):
        self.write_queue.put(("log", (self.session_id, time.time(), level, logger_name, message)))

    def save_signal(self, symbol, side, price, data_dict):
        import json
        self.write_queue.put(("signal", (self.session_id, time.time(), symbol, side, price, json.dumps(data_dict))))

    def save_weight(self, indicator, weight):
        conn = self.connection
        conn.execute("INSERT OR REPLACE INTO model_weights (indicator, weight) VALUES (?, ?)", (indicator, weight))
        conn.commit()

    def get_weights(self):
        cursor = self.connection.execute("SELECT indicator, weight FROM model_weights")
        return dict(cursor.fetchall())

    def save_strategy_state(self, strategy_id, key, value):
        conn = self.connection
        conn.execute("INSERT OR REPLACE INTO strategy_state (strategy_id, key, value) VALUES (?, ?, ?)", (strategy_id, key, str(value)))
        conn.commit()

    def get_strategy_state(self, strategy_id, key):
        cursor = self.connection.execute("SELECT value FROM strategy_state WHERE strategy_id = ? AND key = ?", (strategy_id, key))
        row = cursor.fetchone()
        return row[0] if row else None

    def save_trade(self, strategy_id, symbol, side, entry_ts, entry_price, qty, exit_ts=None, exit_price=None, pnl=None, exit_type=None):
        self.write_queue.put(("trade", (self.session_id, strategy_id, symbol, side, entry_ts, entry_price, qty, exit_ts, exit_price, pnl, exit_type)))

    def save_discovered_assets(self, assets_list):
        assets_str = ",".join(assets_list)
        conn = self.connection
        conn.execute("DELETE FROM discovered_assets")
        conn.execute("INSERT INTO discovered_assets (timestamp, assets) VALUES (?, ?)", (time.time(), assets_str))
        conn.commit()

    def get_discovered_assets(self):
        cursor = self.connection.execute("SELECT timestamp, assets FROM discovered_assets LIMIT 1")
        row = cursor.fetchone()
        if row:
            return row[0], row[1].split(",")
        return 0, []

    def get_recent_ticks(self, symbol, limit=1000):
        cursor = self.connection.execute(
            "SELECT timestamp, price, side, size FROM ticks WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
            (symbol, limit)
        )
        return cursor.fetchall()[::-1]

    def get_recent_candles(self, symbol, timeframe, limit=500):
        cursor = self.connection.execute("""
            SELECT timestamp, open, high, l, close, volume
            FROM (
                SELECT timestamp, open, high, low as l, close, volume
                FROM candles
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp DESC LIMIT ?
            ) ORDER BY timestamp ASC
        """, (symbol, timeframe, limit))
        return cursor.fetchall()

    def get_candle_range_stats(self, symbol, timeframe, start_ts, end_ts):
        cursor = self.connection.execute("""
            SELECT MIN(timestamp), MAX(timestamp), COUNT(*)
            FROM candles
            WHERE symbol = ? AND timeframe = ? AND timestamp >= ? AND timestamp <= ?
        """, (symbol, timeframe, start_ts, end_ts))
        return cursor.fetchone()

    def get_candles_in_range(self, symbol, timeframe, start_ts, end_ts):
        cursor = self.connection.execute("""
            SELECT timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol = ? AND timeframe = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, (symbol, timeframe, start_ts, end_ts))
        return cursor.fetchall()

    def get_all_candle_stats(self) -> Dict[str, Dict[str, Dict[str, float]]]:
        """
        [REPAIR-20260702] Fetches coverage stats for all symbols and timeframes in one query.
        Returns {symbol: {tf: {'count': N, 'min': T1, 'max': T2, 'is_exhausted': bool}}}
        """
        cursor = self.connection.execute("""
            SELECT c.symbol, c.timeframe, COUNT(*), MIN(c.timestamp), MAX(c.timestamp), m.is_exhausted
            FROM candles c
            LEFT JOIN asset_metadata m ON c.symbol = m.symbol AND c.timeframe = m.timeframe
            GROUP BY c.symbol, c.timeframe
        """)
        stats = {}
        for sym, tf, count, t_min, t_max, exhausted in cursor.fetchall():
            if sym not in stats: stats[sym] = {}
            stats[sym][tf] = {'count': count, 'min': t_min, 'max': t_max, 'is_exhausted': bool(exhausted)}
        return stats

    def has_data_gaps(self, symbol: str, timeframe: str, start_ts: float, end_ts: float, stats_cache: dict = None) -> bool:
        """
        [REPAIR-20260707] Fast-check for gaps with Listing-Awareness.
        """
        tf_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
            "1H": 3600, "4H": 14400, "1D": 86400
        }
        step = tf_seconds.get(timeframe, 60)

        # 1. Check Metadata for Listing Completeness
        is_exhausted = False
        if stats_cache and symbol in stats_cache and timeframe in stats_cache[symbol]:
            s = stats_cache[symbol][timeframe]
            is_exhausted = s.get('is_exhausted', False)

            # NOTE: "* 60" below means "60 candles' worth of time" -- that's
            # 1 hour of tolerance for a 1m timeframe, but scales up for
            # coarser ones (e.g. ~60 days for 1D). Left as-is here since
            # changing the actual tolerance is a judgment call about intended
            # behavior, not a straightforward bug fix -- flagging it for a
            # deliberate decision rather than changing it silently.

            # End must be covered (60 candles' worth of tolerance, see note above)
            if s['max'] < end_ts - step * 60: return True

            # If not exhausted, start must be covered (60 candles' worth of tolerance, see note above)
            if not is_exhausted and s['min'] > start_ts + step * 60: return True

            # Check internal continuity based on what WE HAVE
            # We allow 5 candles tolerance for minor exchange maintenance
            expected_total = int((s['max'] - s['min']) / step) + 1
            if s['count'] < expected_total - 5:
                return True # Internal gaps found in cache

            # If start is covered (or exhausted) and end is covered and count matches, it's complete
            return False

        if stats_cache and symbol not in stats_cache:
             # Check if we are exhausted even if no candles exist
             cursor = self.connection.execute("SELECT is_exhausted FROM asset_metadata WHERE symbol=? AND timeframe=?", (symbol, timeframe))
             row = cursor.fetchone()
             if row and bool(row[0]): return False # Exhausted with 0 candles is "complete" for its history
             return True
        else:
            cursor = self.connection.execute("SELECT is_exhausted FROM asset_metadata WHERE symbol=? AND timeframe=?", (symbol, timeframe))
            row = cursor.fetchone()
            is_exhausted = bool(row[0]) if row else False

        # 2. Detailed range check (query DB)
        cursor = self.connection.execute("""
            SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM candles
            WHERE symbol = ? AND timeframe = ? AND timestamp >= ? AND timestamp <= ?
        """, (symbol, timeframe, start_ts, end_ts))
        res = cursor.fetchone()
        if not res or res[0] == 0: return True
        count, first, last = res

        # Coverage check
        if last < end_ts - step * 60: return True
        if not is_exhausted and first > start_ts + step * 60: return True

        # Continuity Check
        expected_in_range = int((last - first) / step) + 1
        if count < expected_in_range - 5:
            return True

        return False

    def get_data_gaps(self, symbol: str, timeframe: str, start_ts: float, end_ts: float, merge_threshold: int = 10, stats_cache: dict = None) -> list:
        """
        [REPAIR-20260708] Improved Gap Detection.
        Identifies actual missing segments by comparing consecutive timestamps.

        [FIX] Listing-Awareness: mirrors the same check has_data_gaps() already
        does. If we've already confirmed (via mark_exhausted) that this
        symbol/timeframe's history doesn't reach back to start_ts -- e.g. a
        coin that was only listed after our configured start date -- we stop
        reporting that unreachable span as a gap. Without this, callers would
        be told, forever, that data is "missing" for a time range that will
        never have any data, simply because it's earlier than the asset
        existed.

        In plain terms: this answers "which specific time ranges are we
        missing candles for, between start_ts and end_ts?" -- returned as a
        list of (gap_start, gap_end) pairs, already merged where they're
        close enough together (within `merge_threshold` candles) that it's
        not worth treating them as separate download requests.

        `stats_cache`, if provided (see get_all_candle_stats), is used to look
        up the exhausted flag without an extra query -- pass it when the
        caller already has it.
        """
        tf_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
            "1H": 3600, "4H": 14400, "1D": 86400
        }
        step = tf_seconds.get(timeframe, 60)

        # Have we already confirmed the true beginning of this symbol's history?
        if stats_cache and symbol in stats_cache and timeframe in stats_cache[symbol]:
            is_exhausted = stats_cache[symbol][timeframe].get('is_exhausted', False)
        else:
            cursor = self.connection.execute(
                "SELECT is_exhausted FROM asset_metadata WHERE symbol=? AND timeframe=?",
                (symbol, timeframe)
            )
            row = cursor.fetchone()
            is_exhausted = bool(row[0]) if row else False

        # 1. Get all timestamps in range
        cursor = self.connection.execute("""
            SELECT timestamp FROM candles
            WHERE symbol = ? AND timeframe = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, (symbol, timeframe, start_ts, end_ts))
        rows = cursor.fetchall()

        if not rows:
            # No candles at all in range. If we've already confirmed this
            # symbol's history is exhausted (there's genuinely nothing to
            # find), that's a complete state, not a gap.
            if is_exhausted:
                return []
            return [(start_ts, end_ts)]

        timestamps = [row[0] for row in rows] # Flatten
        gaps = []

        # Check Leading Gap -- skip if we've already confirmed this range is
        # unreachable (the asset didn't exist yet), so we don't keep asking for it.
        if not is_exhausted and timestamps[0] > start_ts + step:
            gaps.append((start_ts, timestamps[0] - step))

        # Check Internal Gaps (always real/fillable -- exhaustion only ever
        # describes the very beginning of an asset's history, never the middle)
        for i in range(len(timestamps) - 1):
            curr_ts = timestamps[i]
            next_ts = timestamps[i+1]
            if next_ts - curr_ts > step * 1.5: # Allow some tolerance
                gaps.append((curr_ts + step, next_ts - step))

        # Check Trailing Gap
        if timestamps[-1] < end_ts - step:
            gaps.append((timestamps[-1] + step, end_ts))

        # Merge overlapping or adjacent gaps
        if not gaps: return []
        gaps.sort()
        merged = [gaps[0]]
        for curr in gaps[1:]:
            prev = merged[-1]
            # [FIX] This used to be a hardcoded "* 10" regardless of what
            # merge_threshold the caller passed in -- the parameter existed
            # but was never actually used. Now it is.
            if curr[0] <= prev[1] + step * merge_threshold:
                merged[-1] = (prev[0], max(prev[1], curr[1]))
            else:
                merged.append(curr)
        return merged

    def check_candle_exists(self, symbol, timeframe, timestamp):
        cursor = self.connection.execute("""
            SELECT 1 FROM candles
            WHERE symbol = ? AND timeframe = ? AND timestamp = ?
        """, (symbol, timeframe, timestamp))
        return cursor.fetchone() is not None

    def purge_old_data(self, tick_retention_seconds=3600, candle_retention_days=90):
        self.write_queue.put(("purge", (tick_retention_seconds, candle_retention_days)))
        self.purge_old_sessions()

    def purge_old_sessions(self, keep_sessions=3):
        self.write_queue.put(("purge_sessions", keep_sessions))

    def mark_exhausted(self, symbol, timeframe, earliest_ts):
        """[REPAIR-20260707] Persists that we reached the beginning of history."""
        self.write_queue.put(("metadata", (symbol, timeframe, earliest_ts, 1)))

    def stop(self):
        self.stop_event.set()
        self.worker_thread.join()
        if self._conn:
            self._conn.close()
