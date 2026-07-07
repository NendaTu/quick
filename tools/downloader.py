#!/usr/bin/env python3
"""
[TECH-001] Standalone Historical Data Downloader

Downloads 4 years of historical candle data for all configured assets and timeframes.
Respects API rate limits and utilizes range-based gap detection to avoid redundant downloads.
"""

import asyncio
import logging
import sys
import os
import time
import math
import random
from datetime import datetime, timedelta
import pytz

# Ensure project root is in path
sys.path.append(os.getcwd())

from config import BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE, ASSETS_COUNT, ASSET_OMITTED, AVAILABLE_TIMEFRAMES, MAX_START_DATE, MAX_END_DATE, TF_SECONDS
from database import Database
from bitget_client import BitGetClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("downloader")

# Configuration
from engine.exchanges.bitget import BitgetExchange
CONCURRENCY_LIMIT = BitgetExchange.DEFAULT_CONCURRENCY
GLOBAL_RATE_LIMIT = BitgetExchange.DEFAULT_RPS
BATCH_SIZE = 200

class Progress:
    def __init__(self, total, label="Progress"):
        self.total = total
        self.current = 0
        self.label = label
        self.start_time = time.time()
        self.last_update = 0
        self._last_line_len = 0

    def update(self, amount=1):
        self.current += amount
        now = time.time()
        # Throttle to 5 seconds unless complete
        if now - self.last_update < 5 and self.current < self.total:
            return

        self.last_update = now
        pct = min(100.0, (self.current / self.total) * 100) if self.total > 0 else 100.0
        elapsed = now - self.start_time

        # EMA rate smoothing
        current_rate = self.current / elapsed if elapsed > 0 else 0
        if not hasattr(self, "_last_rate"): self._last_rate = current_rate
        self._last_rate = (self._last_rate * 0.9) + (current_rate * 0.1)

        eta = (self.total - self.current) / self._last_rate if self._last_rate > 0 else 0

        # Format: ASSET: TF (PCT% / ETA s)
        msg = f"\r{self.label} ({int(pct)}% / {int(eta)}s) Elapsed: {int(elapsed)}s"
        padding = max(0, self._last_line_len - len(msg))
        full_msg = msg + (" " * padding)

        sys.stdout.write(full_msg)
        sys.stdout.flush()
        self._last_line_len = len(msg)

        if self.current >= self.total:
            print()

async def discover_assets(client: BitGetClient) -> list:
    log.info(f"Discovering top {ASSETS_COUNT} assets by volume...")
    tickers = await client.get_tickers()
    sorted_tickers = sorted(tickers, key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)

    discovered = []
    for t in sorted_tickers:
        sym = t["symbol"]
        if sym.endswith("USDT") and sym not in ASSET_OMITTED:
            if sym.replace("USDT", "") in ["USDC", "DAI", "BUSD", "EUR", "GBP"]:
                continue
            discovered.append(sym)
            if len(discovered) >= ASSETS_COUNT:
                break
    return discovered

class RateLimiter:
    def __init__(self, rps):
        self.interval = 1.0 / rps
        self.last_call = 0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            now = time.time()
            wait_time = self.last_call + self.interval - now
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self.last_call = time.time()

async def download_asset_tf(client: BitGetClient, db: Database, asset: str, tf: str, semaphore: asyncio.Semaphore, limiter: RateLimiter, progress: Progress):
    """
    Downloads gaps for a single asset/timeframe.
    Updates the shared GlobalProgress bar.
    """
    step = TF_SECONDS.get(tf, 60)

    start_ts = MAX_START_DATE.timestamp()
    end_ts = MAX_END_DATE.timestamp()

    # [REPAIR-20260702] Use merged gaps to reduce round-trips
    gaps = db.get_data_gaps(asset, tf, start_ts, end_ts, merge_threshold=10)
    if not gaps:
        return

    async def fetch_chunk(chunk_end_ms, target_start_ms, target_end_ms):
        # [REPAIR-20260707] Controlled request-level concurrency
        async with semaphore:
            try:
                await limiter.wait()
                response = await client.request("GET", "/api/v2/mix/market/history-candles", params={
                    "symbol": asset, "productType": "usdt-futures", "granularity": tf,
                    "endTime": str(chunk_end_ms), "limit": "200"
                })

                if response.get("code") == "00000":
                    data = response.get("data", [])
                    if not data: return 0

                    valid_count = 0
                    for c in data:
                        ts_ms = int(c[0])
                        if ts_ms < target_start_ms: continue
                        if ts_ms > target_end_ms: continue

                        db.save_candle(asset, tf, ts_ms / 1000, float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5]))
                        valid_count += 1

                    progress.update(valid_count)
                    return valid_count
            except Exception as e:
                log.error(f"Error in fetch_chunk {asset} {tf}: {e}")
            return 0

    for gap_start, gap_end in gaps:
        target_start_ms = int(gap_start * 1000)
        target_end_ms = int(gap_end * 1000)

        # Calculate how many 200-candle chunks we need
        total_gap_ms = target_end_ms - target_start_ms
        chunk_ms = 200 * step * 1000
        num_chunks = math.ceil(total_gap_ms / chunk_ms)

        # [REPAIR-20260702] Sequential chunking to prevent freeze
        for i in range(num_chunks):
            chunk_end_ms = target_end_ms - (i * chunk_ms)
            if chunk_end_ms <= target_start_ms: break
            await fetch_chunk(chunk_end_ms, target_start_ms, target_end_ms)

async def main():
    db = Database()
    client = BitGetClient(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE)

    try:
        assets = await discover_assets(client)

        # [REPAIR-20260702] Optimized Startup Check
        start_ts = MAX_START_DATE.timestamp()
        end_ts = MAX_END_DATE.timestamp()

        # Use single-query stats to avoid N+1 startup freeze
        stats_cache = db.get_all_candle_stats()

        completed_assets = []
        remaining_assets = []

        for asset in assets:
            is_complete = True
            for tf in AVAILABLE_TIMEFRAMES:
                if db.has_data_gaps(asset, tf, start_ts, end_ts, stats_cache=stats_cache):
                    is_complete = False; break
            if is_complete: completed_assets.append(asset)
            else: remaining_assets.append(asset)

        # [REPAIR-20260702] Hard-coded log format as requested
        # [REPAIR-20260707] Always show these lines to ensure transparency
        log.info(f"{len(completed_assets)} of {len(assets)} assets have complete data across {len(AVAILABLE_TIMEFRAMES)} timeframes.")

        if not remaining_assets:
            log.info("All assets are already complete. Nothing to download.")
            db.stop(); return

        log.info(f"Starting download for {len(remaining_assets)} assets across {len(AVAILABLE_TIMEFRAMES)} timeframes...")

        # [REPAIR-20260707] Calculate total candles for a GLOBAL progress bar
        total_candles = 0

        # This pass is fast because it uses the stats_cache / fast gap check
        for asset in remaining_assets:
            for tf in AVAILABLE_TIMEFRAMES:
                gaps = db.get_data_gaps(asset, tf, start_ts, end_ts, merge_threshold=10)
                if gaps:
                    total_candles += sum((g[1] - g[0] + TF_SECONDS[tf]) for g in gaps) / TF_SECONDS[tf]

        global_progress = Progress(int(total_candles), label=f"Acquisition: {len(remaining_assets)} Assets")

        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        limiter = RateLimiter(GLOBAL_RATE_LIMIT)

        # [REPAIR-20260707] Worker Pool Pattern
        # Instead of creating thousands of tasks, we use a controlled set of workers
        # to process the download queue. This ensures event loop stability and
        # prevents the application from "freezing" under heavy task load.
        queue = asyncio.Queue()
        for asset in remaining_assets:
            for tf in AVAILABLE_TIMEFRAMES:
                queue.put_nowait((asset, tf))

        async def download_worker():
            while not queue.empty():
                try:
                    asset, tf = queue.get_nowait()
                    await download_asset_tf(client, db, asset, tf, semaphore, limiter, global_progress)
                    queue.task_done()
                except asyncio.QueueEmpty:
                    break
                except Exception as e:
                    log.error(f"Worker Error: {e}")

        # Number of workers matches concurrency limit
        worker_count = CONCURRENCY_LIMIT
        workers = [asyncio.create_task(download_worker()) for _ in range(worker_count)]

        await asyncio.gather(*workers)

        log.info("Historical candle download complete.")

        # TODO: Implement optional tick download here in future iteration

    finally:
        await client.close()
        db.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Downloader interrupted by user.")
