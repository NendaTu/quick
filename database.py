import sqlite3
import time
import logging
import asyncio
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
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks (symbol, timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candles_symbol_tf_time ON candles (symbol, timeframe, timestamp)")

    def _write_worker(self):
        conn = sqlite3.connect(self.db_path)
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

    def get_recent_ticks(self, symbol, limit=1000):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT timestamp, price, side, size FROM ticks WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                (symbol, limit)
            )
            return cursor.fetchall()[::-1]

    def get_recent_candles(self, symbol, timeframe, limit=500):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT timestamp, open, high, low, close, volume
                FROM candles
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (symbol, timeframe, limit))
            return cursor.fetchall()[::-1]

    def purge_old_data(self, tick_retention_seconds=3600, candle_retention_days=7):
        now = time.time()
        # Direct execution for maintenance
        with sqlite3.connect(self.db_path) as conn:
            res_ticks = conn.execute("DELETE FROM ticks WHERE timestamp < ?", (now - tick_retention_seconds,))
            res_candles = conn.execute("DELETE FROM candles WHERE timestamp < ?", (now - candle_retention_days * 86400,))
            log.info(f"Purged {res_ticks.rowcount} old ticks and {res_candles.rowcount} old candles.")

    def stop(self):
        self.stop_event.set()
        self.worker_thread.join()
