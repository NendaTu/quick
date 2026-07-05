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
MAX_LOOKBACK_YEARS = 4
CONCURRENCY_LIMIT = 5 # Strict to allow concurrent bot usage
BATCH_SIZE = 200 # Bitget limit per request

class Progress:
    def __init__(self, total, label="Progress"):
        self.total = total
        self.current = 0
        self.label = label
        self.start_time = time.time()

    def update(self, amount=1):
        self.current += amount
        pct = (self.current / self.total) * 100 if self.total > 0 else 100
        elapsed = time.time() - self.start_time
        rate = self.current / elapsed if elapsed > 0 else 0
        eta = (self.total - self.current) / rate if rate > 0 else 0

        sys.stdout.write(f"\r{self.label}: [{self.current}/{self.total}] {pct:.1f}% | ETA: {int(eta)}s  ")
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

async def download_asset_tf(client: BitGetClient, db: Database, asset: str, tf: str, semaphore: asyncio.Semaphore):
    tf_seconds = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400, "1D": 86400}
    step = tf_seconds.get(tf, 60)

    end_dt = datetime.now(pytz.UTC)
    start_dt = end_dt - timedelta(days=365 * MAX_LOOKBACK_YEARS)

    start_ts = start_dt.timestamp()
    end_ts = end_dt.timestamp()

    # Find gaps in DB
    gaps = db.get_data_gaps(asset, tf, start_ts, end_ts)
    if not gaps:
        return

    for gap_start, gap_end in gaps:
        async with semaphore:
            log.info(f"Downloading {asset} {tf} gap: {datetime.fromtimestamp(gap_start, tz=pytz.UTC)} -> {datetime.fromtimestamp(gap_end, tz=pytz.UTC)}")

            current_end_ms = int(gap_end * 1000)
            target_start_ms = int(gap_start * 1000)

            expected = (gap_end - gap_start) / step
            progress = Progress(max(1, int(expected)), label=f"  {asset} {tf}")

            while current_end_ms > target_start_ms:
                try:
                    candles = await client.request("GET", "/api/v2/mix/market/history-candles", params={
                        "symbol": asset,
                        "productType": "usdt-futures",
                        "granularity": tf,
                        "endTime": str(current_end_ms),
                        "limit": str(BATCH_SIZE)
                    })

                    data = candles.get("data", [])
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
                    await asyncio.sleep(0.1) # Aggressive rate limit safety
                except Exception as e:
                    log.error(f"Error downloading {asset} {tf} at {current_end_ms}: {e}")
                    await asyncio.sleep(1.0)

async def main():
    db = Database()
    client = BitGetClient(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE)

    try:
        assets = await discover_assets(client)
        log.info(f"Starting download for {len(assets)} assets across {len(AVAILABLE_TIMEFRAMES)} timeframes...")

        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

        # Download candles (High priority)
        tasks = []
        for asset in assets:
            for tf in AVAILABLE_TIMEFRAMES:
                tasks.append(download_asset_tf(client, db, asset, tf, semaphore))

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
