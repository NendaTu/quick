import sqlite3
import time
import logging
import threading
import queue

log = logging.getLogger("scalper.database")

class Database:
    def __init__(self, db_path="market_data.db"):
        self.db_path = db_path
        self._init_db()
        self.write_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread = threading.Thread(target=self._write_worker, daemon=True)
        self.worker_thread.start()

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
                    for _ in range(100):
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

    def save_discovered_assets(self, assets_list):
        assets_str = ",".join(assets_list)
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute("DELETE FROM discovered_assets")
            conn.execute("INSERT INTO discovered_assets (timestamp, assets) VALUES (?, ?)", (time.time(), assets_str))
            conn.commit()

    def get_discovered_assets(self):
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            cursor = conn.execute("SELECT timestamp, assets FROM discovered_assets LIMIT 1")
            row = cursor.fetchone()
            if row:
                return row[0], row[1].split(",")
        return 0, []

    def get_recent_ticks(self, symbol, limit=1000):
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout=10000")
            cursor = conn.execute(
                "SELECT timestamp, price, side, size FROM ticks WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                (symbol, limit)
            )
            return cursor.fetchall()[::-1]

    def get_recent_candles(self, symbol, timeframe, limit=500):
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout=10000")
            cursor = conn.execute("""
                SELECT timestamp, open, high, low, close, volume
                FROM candles
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (symbol, timeframe, limit))
            return cursor.fetchall()[::-1]

    def purge_old_data(self, tick_retention_seconds=3600, candle_retention_days=7):
        self.write_queue.put(("purge", (tick_retention_seconds, candle_retention_days)))
        self.purge_old_sessions()

    def purge_old_sessions(self, keep_sessions=3):
        self.write_queue.put(("purge_sessions", keep_sessions))

    def stop(self):
        self.stop_event.set()
        self.worker_thread.join()
