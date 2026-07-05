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
from datetime import datetime, timedelta
import pytz

# Ensure project root is in path
sys.path.append(os.getcwd())

from config import BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE, ASSETS_COUNT, ASSET_OMITTED, AVAILABLE_TIMEFRAMES
from database import Database
from bitget_client import BitGetClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("downloader")

# Configuration
CONCURRENCY_LIMIT = 2
GLOBAL_RATE_LIMIT = 8 # Increased slightly, but added 429 backoff logic
BATCH_SIZE = 200

class Progress:
    def __init__(self, total, label="Progress"):
        self.total = total
        self.current = 0
        self.label = label
        self.start_time = time.time()
        self.last_update = 0

    def update(self, amount=1):
        self.current += amount
        now = time.time()
        # Throttle to 5 seconds unless complete
        if now - self.last_update < 5 and self.current < self.total:
            return

        self.last_update = now
        pct = (self.current / self.total) * 100 if self.total > 0 else 100
        elapsed = now - self.start_time
        rate = self.current / elapsed if elapsed > 0 else 0
        eta = (self.total - self.current) / rate if rate > 0 else 0

        # Format: ASSET: TF (PCT% / ETA s)
        sys.stdout.write(f"\r{self.label} ({int(pct)}% / {int(eta)}s)    ")
        sys.stdout.flush()
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

async def download_asset_tf(client: BitGetClient, db: Database, asset: str, tf: str, semaphore: asyncio.Semaphore, limiter: RateLimiter):
    from backtest import MAX_START_DATE, MAX_END_DATE

    tf_seconds = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400, "1D": 86400}
    step = tf_seconds.get(tf, 60)

    start_ts = MAX_START_DATE.timestamp()
    end_ts = MAX_END_DATE.timestamp()

    # Find gaps in DB
    gaps = db.get_data_gaps(asset, tf, start_ts, end_ts)
    if not gaps:
        return

    # Total expected candles across all gaps
    total_expected = sum((g[1] - g[0]) for g in gaps) / step
    progress = Progress(max(1, int(total_expected)), label=f"{asset}: {tf}")

    for gap_start, gap_end in gaps:
        async with semaphore:
            log.debug(f"Downloading {asset} {tf} gap: {datetime.fromtimestamp(gap_start, tz=pytz.UTC)} -> {datetime.fromtimestamp(gap_end, tz=pytz.UTC)}")

            current_end_ms = int(gap_end * 1000)
            target_start_ms = int(gap_start * 1000)

            while current_end_ms > target_start_ms:
                try:
                    await limiter.wait()

                    response = await client.request("GET", "/api/v2/mix/market/history-candles", params={
                        "symbol": asset,
                        "productType": "usdt-futures",
                        "granularity": tf,
                        "endTime": str(current_end_ms),
                        "limit": str(BATCH_SIZE)
                    })

                    # [TECH-001] Explicit 429 handling with backoff
                    if response.get("code") == "429" or response.get("code") == "400031":
                        log.warning(f"Rate limit hit for {asset} {tf}, backing off...")
                        await asyncio.sleep(5.0)
                        continue

                    data = response.get("data", [])
                    if not data:
                        break

                    valid_count = 0
                    for c in data:
                        ts_ms = int(c[0])
                        o, h, l, cl, v = map(float, c[1:6])

                        if ts_ms < target_start_ms:
                            current_end_ms = 0
                            continue

                        db.save_candle(asset, tf, ts_ms / 1000, o, h, l, cl, v)
                        valid_count += 1
                        current_end_ms = min(current_end_ms, ts_ms - 1)

                    if valid_count == 0:
                        break

                    progress.update(len(data))
                except Exception as e:
                    log.error(f"Error downloading {asset} {tf} at {current_end_ms}: {e}")
                    await asyncio.sleep(2.0)

async def main():
    db = Database()
    client = BitGetClient(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE)

    try:
        assets = await discover_assets(client)
        log.info(f"Starting download for {len(assets)} assets across {len(AVAILABLE_TIMEFRAMES)} timeframes...")

        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        limiter = RateLimiter(GLOBAL_RATE_LIMIT)

        # Download candles (High priority)
        tasks = []
        for asset in assets:
            for tf in AVAILABLE_TIMEFRAMES:
                tasks.append(download_asset_tf(client, db, asset, tf, semaphore, limiter))

        await asyncio.gather(*tasks)

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
