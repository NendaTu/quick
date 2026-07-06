import sqlite3
import time
import logging
import threading
import queue

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

    def get_data_gaps(self, symbol: str, timeframe: str, start_ts: float, end_ts: float, merge_threshold: int = 10) -> list:
        """
        [TECH-001] Identifies holes in the historical data for a specific asset/timeframe.
        [REPAIR-20260702] Implements Gap Merging: merges gaps separated by <= merge_threshold candles.

        Returns a list of (gap_start, gap_end) tuples representing missing periods.
        """
        # 1. Fetch all existing timestamps in the target range, sorted chronologically
        cursor = self.connection.execute("""
            SELECT timestamp FROM candles
            WHERE symbol = ? AND timeframe = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, (symbol, timeframe, start_ts, end_ts))
        rows = cursor.fetchall()

        if not rows:
            return [(start_ts, end_ts)]

        tf_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
            "1H": 3600, "4H": 14400, "1D": 86400
        }
        step = tf_seconds.get(timeframe, 60)

        raw_gaps = []
        # Check leading gap
        if rows[0][0] > start_ts + step:
            raw_gaps.append((start_ts, rows[0][0] - step))

        # Check internal gaps
        for i in range(len(rows) - 1):
            curr_ts = rows[i][0]
            next_ts = rows[i+1][0]
            if next_ts > curr_ts + step * 1.1:
                raw_gaps.append((curr_ts + step, next_ts - step))

        # Check trailing gap
        if rows[-1][0] < end_ts - step:
            raw_gaps.append((rows[-1][0] + step, end_ts))

        if not raw_gaps:
            return []

        # 2. Merge Gaps [REPAIR-20260702]
        merged_gaps = []
        if raw_gaps:
            curr_start, curr_end = raw_gaps[0]
            for i in range(1, len(raw_gaps)):
                next_start, next_end = raw_gaps[i]
                # If distance between gaps is <= threshold candles
                if next_start - curr_end <= step * (merge_threshold + 1):
                    curr_end = next_end
                else:
                    merged_gaps.append((curr_start, curr_end))
                    curr_start, curr_end = next_start, next_end
            merged_gaps.append((curr_start, curr_end))

        return merged_gaps

    def check_candle_exists(self, symbol, timeframe, timestamp):
        cursor = self.connection.execute("""
            SELECT 1 FROM candles
            WHERE symbol = ? AND timeframe = ? AND timestamp = ?
        """, (symbol, timeframe, timestamp))
        return cursor.fetchone() is not None

    def purge_old_data(self, tick_retention_seconds=3600, candle_retention_days=7):
        self.write_queue.put(("purge", (tick_retention_seconds, candle_retention_days)))
        self.purge_old_sessions()

    def purge_old_sessions(self, keep_sessions=3):
        self.write_queue.put(("purge_sessions", keep_sessions))

    def stop(self):
        self.stop_event.set()
        self.worker_thread.join()
        if self._conn:
            self._conn.close()
