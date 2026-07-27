#!/usr/bin/env python3
"""
[TECH-001] Standalone Historical Data Downloader
=================================================

WHAT THIS SCRIPT DOES (plain-language summary):
------------------------------------------------
This script fills in historical price data ("candles" -- the open / high /
low / close / volume bars used for charting, backtesting, and strategy
research) for our tracked crypto assets, covering the date range configured
in config.py (MAX_START_DATE to MAX_END_DATE) across every timeframe we care
about (config.AVAILABLE_TIMEFRAMES, e.g. 1-minute, 1-hour, 1-day, ...).

Step by step, it:
  1. Asks Bitget which assets are currently trading the most volume, and
     picks the top N (config.ASSETS_COUNT).
  2. Checks our local database to see what data we already have for each of
     those assets, at every timeframe.
  3. Downloads ONLY what's missing. It never re-downloads data it already
     has, so it is always safe -- and usually fast -- to run again.
  4. Prints a short coverage report and a live progress bar while it works.

IS IT SAFE TO STOP AND RE-RUN? Yes. If you press Ctrl+C, the process gets
killed, or your connection drops, just run the script again. It resumes
exactly where it left off: nothing gets re-downloaded, and any asset/
timeframe we've already confirmed is "as complete as it can possibly be"
(for example, a coin that only started trading a year ago, so it will never
have data going back further than that) is remembered and skipped for good.

HOW LONG DOES THIS TAKE? For a full run starting from an empty database,
across every configured asset and timeframe, this can take DAYS, not
minutes -- we deliberately throttle ourselves well under Bitget's rate
limits so we don't get temporarily blocked. Watch the progress bar for a
live estimate once the download phase begins. Re-runs (once most of the
data already exists) are much faster, since there's little left to fetch.

If a run finishes with a warning about "chunks that hit an API error", that
is NOT data loss -- it just means a small number of requests failed even
after BitGetClient's own retries (rare, but can happen). Simply run the
script again and gap-detection will pick those pieces back up automatically.

NOTES FOR DEVELOPERS:
------------------------------------------------
- Rate limiting happens in exactly ONE place: inside BitGetClient itself,
  via the RateLimiter instance we hand it at construction time (see
  `shared_rate_limiter` below). This script does not run a second,
  independent limiter -- an earlier version did, and it turned out to be a
  harmless-but-fragile leftover from before BitGetClient gained its own
  internal rate limiting. Don't reintroduce a second one; it will either do
  nothing (if it happens to match) or fight with the client's own limiter
  (if it doesn't).
- "Missing data" is determined by Database.get_data_gaps() /
  has_data_gaps(), both of which are "listing-aware": once we've confirmed
  (via Database.mark_exhausted) that an asset's history doesn't reach back
  to MAX_START_DATE -- because it wasn't listed yet -- we stop treating that
  unreachable span as a gap that needs filling.
- Database.save_candle() is a fast, non-blocking handoff to a background
  writer thread (see database.py) -- it's safe to call from inside the
  asyncio event loop without blocking other concurrent workers.
- Gaps for every asset/timeframe pair are computed ONCE, up front, in
  main(), and reused both to size the progress bar and as the actual
  download worklist -- we don't ask the database the same question twice.
"""

import asyncio
import logging
import sys
import os
import time
import math
from typing import Dict, List, Tuple

# Anchor imports to this file's own location (not the current working
# directory) so the script works the same way whether it's launched from the
# project root, from inside tools/, or from anywhere else.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE,
    ASSETS_COUNT, ASSET_OMITTED, AVAILABLE_TIMEFRAMES,
    MAX_START_DATE, MAX_END_DATE, TF_SECONDS,
)
from database import Database
from bitget_client import BitGetClient, RateLimiter
from engine.exchanges.bitget import BitgetExchange

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("downloader")

# --- Tuning constants ---
# Mirrors the limits BitgetExchange itself uses for the live engine's market
# data client, so this standalone script behaves the same way the engine
# would if it were doing this backfill itself.
CONCURRENCY_LIMIT = BitgetExchange.DEFAULT_CONCURRENCY  # how many chunk fetches can be in flight at once
TARGET_RPS = BitgetExchange.DEFAULT_RPS                 # requests/second we aim for -- see shared_rate_limiter in main()
BATCH_SIZE = 200  # Bitget's max candles per history-candles request


class Progress:
    """
    A simple, dependency-free progress bar for the terminal.

    Prints at most once every 5 seconds while work is ongoing, so a fast run
    doesn't flood the terminal -- but always prints exactly one final line
    once the target is reached, even if that lands in the middle of a
    5-second quiet window, and never prints again after that.

    (An earlier version kept printing on every single update once `current`
    passed `total` -- which can happen whenever the up-front estimate turns
    out to be slightly low, e.g. two adjacent requests both returning a
    boundary candle -- and could flood the terminal for the rest of a run.)
    """
    def __init__(self, total: int, label: str = "Progress"):
        self.total = total
        self.current = 0
        self.label = label
        self.start_time = time.time()
        self.last_update = 0
        self._last_line_len = 0
        self._last_rate = 0.0
        self._finished = False  # once True, update() becomes a no-op

    def update(self, amount: int = 1):
        if self._finished:
            return

        self.current += amount
        now = time.time()
        just_finished = self.current >= self.total

        # Throttle to once every 5 seconds, except always show the final line.
        if not just_finished and (now - self.last_update) < 5:
            return

        self.last_update = now
        pct = min(100.0, (self.current / self.total) * 100) if self.total > 0 else 100.0
        elapsed = now - self.start_time

        # Exponential moving average, so the ETA doesn't jump around wildly
        # between prints.
        current_rate = self.current / elapsed if elapsed > 0 else 0
        self._last_rate = (self._last_rate * 0.9) + (current_rate * 0.1)
        eta = (self.total - self.current) / self._last_rate if self._last_rate > 0 else 0

        msg = f"\r{self.label} ({int(pct)}% / {int(eta)}s) Elapsed: {int(elapsed)}s"
        padding = max(0, self._last_line_len - len(msg))
        sys.stdout.write(msg + (" " * padding))
        sys.stdout.flush()
        self._last_line_len = len(msg)

        if just_finished:
            print()
            self._finished = True


async def discover_assets(client: BitGetClient) -> List[str]:
    """
    Asks Bitget for current trading volume across all USDT-margined perpetual
    futures, and returns the top ASSETS_COUNT symbols -- skipping anything on
    the ASSET_OMITTED list and any stablecoin/fiat-margined pair (we only
    want real, volatile assets here, not e.g. USDC/USDT).
    """
    log.info(f"Discovering top {ASSETS_COUNT} assets by volume...")
    tickers = await client.get_tickers()
    sorted_tickers = sorted(tickers, key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)

    non_asset_bases = ("USDC", "DAI", "BUSD", "EUR", "GBP")

    discovered = []
    for t in sorted_tickers:
        sym = t["symbol"]
        if not sym.endswith("USDT") or sym in ASSET_OMITTED:
            continue
        if sym.removesuffix("USDT") in non_asset_bases:
            continue
        discovered.append(sym)
        if len(discovered) >= ASSETS_COUNT:
            break
    return discovered


async def download_asset_tf(
    client: BitGetClient,
    db: Database,
    asset: str,
    tf: str,
    gaps: List[Tuple[float, float]],
    semaphore: asyncio.Semaphore,
    progress: Progress,
    worker_id: int,
    run_stats: Dict[str, int],
):
    """
    Fetches and saves every missing candle for one asset/timeframe pair.

    `gaps` is the list of (gap_start, gap_end) time ranges we already know
    are missing -- computed once, up front, in main() -- so this function's
    only job is to actually fetch those ranges, BATCH_SIZE candles at a
    time, and save them.
    """
    if not gaps:
        return
    step = TF_SECONDS.get(tf, 60)

    async def fetch_chunk(chunk_end_ms: int, target_start_ms: int, target_end_ms: int) -> int:
        """
        Fetches one batch of up to BATCH_SIZE candles ending at chunk_end_ms,
        keeps only the ones inside our target range, and saves them.

        Returns -1 if Bitget confirms there's no more data further back (we
        reached the true beginning of this asset's history), 0 if nothing
        usable came back this time (including if the request itself
        failed -- see the logging below), or the number of candles saved.
        """
        async with semaphore:
            try:
                response = await client.request("GET", "/api/v2/mix/market/history-candles", params={
                    "symbol": asset,
                    "productType": "USDT-FUTURES",  # must match this exact casing -- used consistently everywhere else in bitget_client.py
                    "granularity": tf,
                    "endTime": str(chunk_end_ms),
                    "limit": str(BATCH_SIZE),
                })

                if response.get("code") == "00000":
                    data = response.get("data", [])
                    if not data:
                        # A successful, empty response means Bitget has no
                        # candles before this point -- we've hit the true
                        # start of this asset's history. Remember that
                        # permanently so future runs don't keep re-checking
                        # a time range that will never have data.
                        db.mark_exhausted(asset, tf, chunk_end_ms / 1000)
                        return -1

                    valid_count = 0
                    for c in data:
                        ts_ms = int(c[0])
                        if ts_ms < target_start_ms or ts_ms > target_end_ms:
                            continue
                        # Bitget candle format: [timestamp, open, high, low, close, baseVolume, quoteVolume]
                        db.save_candle(asset, tf, ts_ms / 1000, float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5]))
                        valid_count += 1

                    progress.update(valid_count)
                    return valid_count

                # We got a response, but Bitget reported an error (bad
                # params, an auth hiccup that outlasted BitGetClient's own
                # retries, etc). BitGetClient already logs the details
                # internally -- this is so THIS run doesn't quietly treat
                # "the request failed" the same as "there's genuinely no
                # data here" (only an empty response with code "00000" means
                # that), and so the operator finds out it happened at all.
                log.warning(
                    f"[{asset} {tf}] worker {worker_id}: chunk ending {chunk_end_ms} "
                    f"got code {response.get('code')} ({response.get('msg', 'no message')}) "
                    f"-- skipping for this run; gap-detection will retry it next time."
                )
                run_stats["failed_chunks"] += 1
                return 0
            except Exception as e:
                log.error(f"[{asset} {tf}] worker {worker_id}: error in fetch_chunk: {e}")
                run_stats["failed_chunks"] += 1
                return 0

    for gap_start, gap_end in gaps:
        target_start_ms = int(gap_start * 1000)
        target_end_ms = int(gap_end * 1000)

        total_gap_ms = target_end_ms - target_start_ms
        chunk_ms = BATCH_SIZE * step * 1000
        num_chunks = math.ceil(total_gap_ms / chunk_ms)

        # Chunks are fetched newest-to-oldest, one at a time (not
        # concurrently) within a single gap. This is deliberate: the -1
        # "beginning of history" signal only means what we think it means if
        # we haven't skipped past older, un-checked chunks first -- fetching
        # out of order could make us mark a range "exhausted" prematurely.
        for i in range(num_chunks):
            chunk_end_ms = target_end_ms - (i * chunk_ms)
            if chunk_end_ms <= target_start_ms:
                break
            result = await fetch_chunk(chunk_end_ms, target_start_ms, target_end_ms)
            if result == -1:
                break  # reached the beginning of this asset's history


def report_coverage(assets: List[str], start_ts: float, end_ts: float, stats_cache: dict):
    """
    Prints a quick summary table: for each asset, roughly what fraction of
    the configured history we actually have, averaged across timeframes.

    For an asset whose history has been confirmed "exhausted" (it started
    trading after MAX_START_DATE), coverage is measured against what's
    actually achievable -- from its real listing date onward -- rather than
    the full configured window. Otherwise a brand-new, perfectly and fully
    backfilled listing would misleadingly show up as permanently incomplete,
    just because it can never reach all the way back to MAX_START_DATE.
    """
    print("\n" + "=" * 60)
    print(f"{'Asset':<15} | {'Coverage %':>10}")
    print("-" * 60)

    total_range_sec = end_ts - start_ts

    for asset in sorted(assets):
        asset_coverage = []
        for tf in AVAILABLE_TIMEFRAMES:
            step = TF_SECONDS.get(tf, 60)
            stat = stats_cache.get(asset, {}).get(tf)

            if not stat:
                asset_coverage.append(0.0)
                continue

            if stat.get("is_exhausted") and stat.get("min") is not None:
                achievable_start = max(start_ts, stat["min"])
                expected_total = int((end_ts - achievable_start) / step) + 1
            else:
                expected_total = int(total_range_sec / step) + 1

            pct = min(100.0, (stat["count"] / expected_total) * 100) if expected_total > 0 else 100.0
            asset_coverage.append(pct)

        avg_pct = sum(asset_coverage) / len(asset_coverage) if asset_coverage else 0.0
        print(f"{asset:<15} | {avg_pct:>9.1f}%")

    print("=" * 60 + "\n")


async def main():
    db = Database()

    # A single, shared rate limiter, used for every request this script
    # makes. IMPORTANT: keep this the only one. BitGetClient enforces it
    # internally on every call to client.request() -- wrapping calls with a
    # second, separate limiter here would just be redundant bookkeeping that
    # happens to line up today (because the numbers match) but would
    # silently drift out of sync the moment either configuration value
    # changed independently.
    shared_rate_limiter = RateLimiter(rps=TARGET_RPS, safety_factor=0.98)
    client = BitGetClient(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE, rate_limiter=shared_rate_limiter)

    # Things worth telling the operator about at the end of the run, without
    # interrupting the run itself.
    run_stats: Dict[str, int] = {"failed_chunks": 0}

    try:
        assets = await discover_assets(client)

        start_ts = MAX_START_DATE.timestamp()
        end_ts = MAX_END_DATE.timestamp()

        # One trip to the database for candle stats, reused below by both the
        # coverage report and the completeness check -- this used to be
        # fetched twice in a row for identical data.
        stats_cache = db.get_all_candle_stats()

        report_coverage(assets, start_ts, end_ts, stats_cache)

        completed_assets = []
        remaining_assets = []
        for asset in assets:
            is_complete = True
            for tf in AVAILABLE_TIMEFRAMES:
                if db.has_data_gaps(asset, tf, start_ts, end_ts, stats_cache=stats_cache):
                    is_complete = False
                    break
            if is_complete:
                completed_assets.append(asset)
            else:
                remaining_assets.append(asset)

        # Brief pause purely so the two log lines below are easy to read as
        # they scroll by in a live terminal. Skipped automatically when
        # output isn't an interactive terminal (e.g. piped to a log file, or
        # run under a scheduler), since there's no one watching it live.
        if sys.stdout.isatty():
            await asyncio.sleep(1.0)
        log.info(f"{len(completed_assets)} of {len(assets)} assets have complete data across {len(AVAILABLE_TIMEFRAMES)} timeframes.")

        if not remaining_assets:
            log.info("All assets are already complete. Nothing to download.")
            return  # cleanup happens once, uniformly, in `finally` below

        if sys.stdout.isatty():
            await asyncio.sleep(1.0)
        log.info(f"Starting download for {len(remaining_assets)} assets across {len(AVAILABLE_TIMEFRAMES)} timeframes...")

        # Work out exactly what's missing, ONCE, for every asset/timeframe
        # pair that still needs work. We reuse this same result both to size
        # the progress bar below and as the actual download worklist further
        # down -- no need to ask the database the same question twice.
        gaps_by_pair: Dict[Tuple[str, str], list] = {}
        total_candles = 0
        for asset in remaining_assets:
            for tf in AVAILABLE_TIMEFRAMES:
                gaps = db.get_data_gaps(asset, tf, start_ts, end_ts, merge_threshold=10, stats_cache=stats_cache)
                gaps_by_pair[(asset, tf)] = gaps
                if gaps:
                    total_candles += sum((g[1] - g[0] + TF_SECONDS[tf]) for g in gaps) / TF_SECONDS[tf]

        global_progress = Progress(int(total_candles), label="Acquisition")
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

        # Worker pool: each worker pulls one (asset, timeframe) pair at a
        # time from the shared queue and fills in its gaps. Only pairs that
        # actually have something missing are queued.
        queue: asyncio.Queue = asyncio.Queue()
        for asset in remaining_assets:
            for tf in AVAILABLE_TIMEFRAMES:
                if gaps_by_pair[(asset, tf)]:
                    queue.put_nowait((asset, tf))

        async def download_worker(worker_id: int):
            while True:
                try:
                    asset, tf = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                log.info(f"Worker {worker_id}: Processing {asset} {tf}...")
                try:
                    await download_asset_tf(
                        client, db, asset, tf,
                        gaps_by_pair[(asset, tf)],
                        semaphore, global_progress, worker_id, run_stats,
                    )
                except Exception as e:
                    log.error(f"Worker {worker_id} error on {asset} {tf}: {e}")

        workers = [asyncio.create_task(download_worker(i)) for i in range(CONCURRENCY_LIMIT)]
        await asyncio.gather(*workers)

        log.info("Historical candle download complete.")
        if run_stats["failed_chunks"] > 0:
            log.warning(
                f"{run_stats['failed_chunks']} chunk(s) hit an API error even after BitGetClient's "
                f"own retries, and were skipped this run. This is not data loss -- it just means "
                f"re-running the script will pick them back up automatically via gap-detection."
            )

        # TODO: Implement optional tick download here in future iteration

    except Exception:
        log.critical("Downloader stopped due to an unexpected error:", exc_info=True)
        raise
    finally:
        await client.close()
        db.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Downloader interrupted by user.")
