import sys
import os
import asyncio
import logging
import multiprocessing
import importlib
import time
import signal
import ast
from typing import List, Dict, Any
from dataclasses import dataclass

# Ensure project root is in path
sys.path.append(os.getcwd())

from config import *
from engine import Engine
from bitget_client import BitGetWSClient, BitGetClient

# Configure logging for the orchestrator
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("compare")

@dataclass
class Variant:
    id: str
    overrides: Dict[str, Any]
    config_file: str = None

class DataCoordinator:
    def __init__(self, symbols: List[str], queues: List[multiprocessing.Queue]):
        self.symbols = symbols
        self.queues = queues
        self.client = BitGetClient(BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE)
        self.preloaded_data = {}

    async def warm_up(self):
        log.info("Coordinator: Starting global warm-up...")
        # Re-use logic from Simulator but simplified for global state
        tickers = await self.client.get_tickers()
        specs = await self.client.get_symbols()
        spec_map = {s['symbol']: s for s in specs}

        discovered_assets = []
        limit = self.preloaded_data.get("ASSETS_COUNT", ASSETS_COUNT)
        sorted_tickers = sorted(tickers, key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)
        for t in sorted_tickers:
            sym = t["symbol"]
            if sym.endswith("USDT") and sym not in ASSET_OMITTED:
                if sym.replace("USDT", "") in ["USDC", "DAI", "BUSD", "EUR", "GBP"]: continue
                discovered_assets.append(sym)
                if len(discovered_assets) >= limit: break

        self.preloaded_data["discovered_assets"] = discovered_assets
        self.preloaded_data["INITIAL_EQUITY"] = INITIAL_EQUITY
        self.preloaded_data["contract_specs"] = {s: spec_map[s] for s in discovered_assets + [BTC_SYMBOL] if s in spec_map}
        self.preloaded_data["leverage_limits"] = {s: float(spec_map[s].get('maxLever', 20)) for s in discovered_assets + [BTC_SYMBOL] if s in spec_map}
        self.preloaded_data["ohlcv"] = {s: {tf: [] for tf in AVAILABLE_TIMEFRAMES} for s in discovered_assets + [BTC_SYMBOL]}
        self.preloaded_data["confluence_history"] = {s: {tf: [] for tf in ["15m", "1H", "4H", "1D", "1W"]} for s in discovered_assets + [BTC_SYMBOL]}
        self.preloaded_data["last_candle_ts"] = {s: {tf: 0 for tf in AVAILABLE_TIMEFRAMES} for s in discovered_assets + [BTC_SYMBOL]}
        self.preloaded_data["last_price"] = {s: float(next((t['lastPr'] for t in tickers if t['symbol'] == s), 1.0)) for s in discovered_assets + [BTC_SYMBOL]}

        semaphore = asyncio.Semaphore(5)
        async def fetch_symbol_data(sym):
            async with semaphore:
                await asyncio.sleep(0.1)
                for tf in AVAILABLE_TIMEFRAMES:
                    limit = 500 if tf == ACTIVE_TIMEFRAME else 100
                    data = await self.client.get_candles(sym, tf, limit=limit)
                    if isinstance(data, list):
                        for c in reversed(data):
                            ts = float(c[0]) / 1000
                            o, h, l, cl, v = map(float, c[1:6])
                            self.preloaded_data["ohlcv"][sym][tf].append({"ts": ts, "o": o, "h": h, "l": l, "c": cl, "v": v})
                            self.preloaded_data["last_candle_ts"][sym][tf] = ts

                for tf in ["15m", "1H", "4H", "1D", "1W"]:
                    c_data = await self.client.get_candles(sym, tf, limit=100)
                    if isinstance(c_data, list):
                        for c in reversed(c_data):
                            ts = float(c[0]) / 1000
                            cl = float(c[4])
                            self.preloaded_data["confluence_history"][sym][tf].append(cl)

        symbols_to_fetch = discovered_assets + [BTC_SYMBOL]
        log.info(f"Coordinator: Fetching data for {len(symbols_to_fetch)} symbols...")
        # Use smaller batches to see progress
        batch_size = 10
        for i in range(0, len(symbols_to_fetch), batch_size):
            batch = symbols_to_fetch[i:i+batch_size]
            log.info(f"Coordinator: Fetching batch {i//batch_size + 1}/{(len(symbols_to_fetch)-1)//batch_size + 1}...")
            await asyncio.gather(*(fetch_symbol_data(s) for s in batch))

        log.info("Coordinator: Global warm-up complete.")

    async def _ws_callback(self, msg):
        # Filter out meta-messages like 'subscribe' events to reduce queue noise
        if "data" not in msg and msg.get("action") != "snapshot":
            return

        for q in self.queues:
            # Non-blocking put to avoid coordinator stalling
            try:
                q.put_nowait(msg)
            except:
                pass

    async def run(self):
        self.ws_client = BitGetWSClient(self.preloaded_data["discovered_assets"] + [BTC_SYMBOL], self._ws_callback)
        try:
            await self.ws_client.run()
        finally:
            await self.client.close()

def variant_runner(variant: Variant, preloaded_data: Dict, input_queue: multiprocessing.Queue, stats_queue: multiprocessing.Queue):
    # Isolated process entry point
    import config
    import logging

    # 1. Apply Overrides BEFORE importing engine
    # This ensures 'from config import *' gets the patched values
    for key, val in variant.overrides.items():
        setattr(config, key, val)

    import engine as engine_module

    # 2. Disable some things for comparison
    config.SHOW_PERIODIC_SUMMARY = False
    config.LOG_SIGNALS = True
    config.LOG_REJECTIONS = True

    # Ensure comparisons don't stop prematurely due to session limits
    config.MAX_TRADES_LIMIT = 999999
    config.MAX_DURATION = 9999999
    config.TOTAL_ROI_LIMIT = 100.0

    # 2.5 Ensure INITIAL_EQUITY sync [CS-004]
    config.INITIAL_EQUITY = preloaded_data.get("INITIAL_EQUITY", INITIAL_EQUITY)

    # 3. Setup Logging to File (Sanitize filename)
    safe_id = variant.id.replace(":", "").replace("/", "_").replace(" ", "_")
    log_file = f"compare/logs/{safe_id}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))

    root_logger = logging.getLogger()
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.INFO)

    # 4. Start Engine
    engine = engine_module.Engine(use_db=False)

    async def run_engine():
        # Setup periodic stats reporting
        async def report_stats():
            while not engine.stop_event.is_set():
                stats = {
                    "id": variant.id,
                    "equity": engine.equity,
                    "total_trades": engine.total_trades,
                    "winning_trades": engine.winning_trades,
                    "losing_trades": engine.losing_trades,
                    "tp_wins": engine.tp_wins,
                    "be_wins": engine.be_wins,
                    "cumulative_pnl": engine.cumulative_pnl,
                    "open_positions": len(engine.open_positions),
                }
                stats_queue.put(stats)
                await asyncio.sleep(5)

        asyncio.create_task(report_stats())
        await engine.start(preloaded_data=preloaded_data, external_feed=input_queue)

        # Cleanup Simulator's BitGetClient session
        if hasattr(engine.exchange, "client") and engine.exchange.client:
            await engine.exchange.client.close()

    try:
        asyncio.run(run_engine())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        # Final stats
        stats = {
            "id": variant.id,
            "equity": engine.equity,
            "total_trades": engine.total_trades,
            "winning_trades": engine.winning_trades,
            "losing_trades": engine.losing_trades,
            "tp_wins": engine.tp_wins,
            "be_wins": engine.be_wins,
            "cumulative_pnl": engine.cumulative_pnl,
            "open_positions": len(engine.open_positions),
            "final": True
        }
        stats_queue.put(stats)

def parse_args() -> List[Variant]:
    variants = [Variant(id="Baseline", overrides={})]

    # Pre-parse overrides for global settings like ASSETS_COUNT
    for arg in sys.argv[1:]:
        if "=" in arg:
            k, v = [x.strip() for x in arg.split("=", 1)]
            if k == "ASSETS_COUNT":
                # Apply globally to Baseline
                try:
                    variants[0].overrides[k] = ast.literal_eval(v)
                except:
                    pass

    if len(sys.argv) > 1:
        if sys.argv[1] == "config":
            # Look in compare/configs/
            for f in os.listdir("compare/configs"):
                if f.endswith(".py"):
                    overrides = {}
                    with open(os.path.join("compare/configs", f), "r") as cf:
                        for line in cf:
                            if "=" in line and not line.startswith("#"):
                                try:
                                    k, v = line.split("=", 1)
                                    overrides[k.strip()] = ast.literal_eval(v.split("#")[0].strip())
                                except:
                                    pass
                    variants.append(Variant(id=f.replace(".py", ""), overrides=overrides, config_file=f))
        else:
            # Parse VAR=VAL args
            for arg in sys.argv[1:]:
                if "=" in arg:
                    k, v = [x.strip() for x in arg.split("=", 1)]
                    try:
                        val = ast.literal_eval(v)
                    except (ValueError, SyntaxError):
                        val = v

                    if k in variants[-1].overrides and variants[-1].id != "Baseline":
                        variants.append(Variant(id=f"Var_{len(variants)}", overrides={k: val}))
                    else:
                        if variants[-1].id == "Baseline":
                            variants.append(Variant(id="Var_1", overrides={k: val}))
                        else:
                            variants[-1].overrides[k] = val

    # Dynamic Renaming based on overrides
    import config as root_config
    all_overridden_keys = set()
    for v in variants[1:]:
        all_overridden_keys.update(v.overrides.keys())

    # Remove ASSETS_COUNT from name tagging if it was global
    all_overridden_keys.discard("ASSETS_COUNT")

    for v in variants:
        if v.id == "Baseline":
            tag = ", ".join([f"{k}={getattr(root_config, k, 'N/A')}" for k in sorted(all_overridden_keys)])
            v.id = f"Baseline: {tag}" if tag else "Baseline"
        elif v.config_file:
            # Keep filename but maybe append overrides if any?
            pass
        else:
            # VAR=VAL variant
            tag = ", ".join([f"{k}={val}" for k, val in sorted(v.overrides.items()) if k != "ASSETS_COUNT"])
            v.id = tag

    return variants

async def main():
    variants = parse_args()
    log.info(f"Starting comparison with {len(variants)} variants: {[v.id for v in variants]}")

    # Ensure required directories exist BEFORE starting variants
    os.makedirs("compare/configs", exist_ok=True)
    os.makedirs("compare/logs", exist_ok=True)

    queues = [multiprocessing.Queue() for _ in variants]
    stats_queue = multiprocessing.Queue()

    # If ASSETS_COUNT is in any variant, use the max of them.
    # Otherwise use the global config.
    assets_overridden = [v.overrides["ASSETS_COUNT"] for v in variants if "ASSETS_COUNT" in v.overrides]
    if assets_overridden:
        assets_limit = max(assets_overridden)
    else:
        assets_limit = ASSETS_COUNT

    coordinator = DataCoordinator(symbols=[], queues=queues)
    coordinator.preloaded_data["ASSETS_COUNT"] = assets_limit
    await coordinator.warm_up()

    # Start DataCoordinator in the background
    coordinator_task = asyncio.create_task(coordinator.run())

    processes = []
    for i, v in enumerate(variants):
        p = multiprocessing.Process(
            target=variant_runner,
            args=(v, coordinator.preloaded_data, queues[i], stats_queue)
        )
        p.start()
        processes.append(p)

    log.info("All variants started. Press CTRL+C to stop and see results.")

    latest_stats = {v.id: {} for v in variants}
    start_time = time.time()

    def print_table():
        elapsed = time.time() - start_time
        hh, rem = divmod(elapsed, 3600)
        mm, ss = divmod(rem, 60)

        print("\n" + "="*110)
        print(f"A/B TEST STATUS | Duration: {int(hh):02d}:{int(mm):02d}:{int(ss):02d}")
        print("-" * 110)
        print(f"{'Variant':<20} | {'PnL (USDT)':>12} | {'ROI%':>8} | {'Win% (TP)':>12} | {'Trades':>8} | {'Open':>5} | {'Equity':>12}")
        print("-" * 110)

        # Sort by PnL
        sorted_ids = sorted(latest_stats.keys(), key=lambda x: latest_stats[x].get("cumulative_pnl", 0), reverse=True)
        winner_id = sorted_ids[0] if latest_stats[sorted_ids[0]] and latest_stats[sorted_ids[0]].get("cumulative_pnl", 0) > 0 else None

        for vid in sorted_ids:
            s = latest_stats[vid]
            if not s:
                print(f"   {vid:<17} | {'WAITING...':>12}")
                continue

            pnl = s.get("cumulative_pnl", 0)
            trades = s.get("total_trades", 0)
            winning = s.get("winning_trades", 0)
            tp_wins = s.get("tp_wins", 0)
            win_rate = (winning / trades * 100) if trades > 0 else 0
            tp_win_rate = (tp_wins / trades * 100) if trades > 0 else 0
            open_p = s.get("open_positions", 0)
            equity = s.get("equity", INITIAL_EQUITY)
            roi = ((equity / INITIAL_EQUITY) - 1) * 100

            prefix = "🏆 " if vid == winner_id else "   "
            print(f"{prefix}{vid:<17} | {pnl:>12.2f} | {roi:>7.1f}% | {win_rate:>5.1f}% ({tp_win_rate:>4.1f}%) | {trades:>8} | {open_p:>5} | {equity:>12.2f}")
        print("="*110 + "\n")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, lambda: stop_event.set())

    try:
        # Initial display
        print_table()

        while not stop_event.is_set():
            # Check for stats updates
            updated = False
            try:
                while True:
                    s = stats_queue.get_nowait()
                    latest_stats[s["id"]] = s
                    updated = True
            except:
                pass

            if updated:
                print_table()

            # Wait for stop signal or timeout
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        log.info("Stopping comparison and cleaning up processes...")

        # 1. Stop Data Coordinator
        if coordinator.ws_client:
            coordinator.ws_client.stop()

        # 2. Signal variants to stop
        for q in queues:
            try:
                q.put_nowait(None)
            except:
                pass

        # 3. Terminate processes
        for p in processes:
            if p.is_alive():
                p.terminate()

        # 4. Wait for them to finish
        for p in processes:
            p.join(timeout=1)
            if p.is_alive():
                p.kill()

        # 5. Final stats grab
        try:
            while True:
                s = stats_queue.get_nowait()
                latest_stats[s["id"]] = s
        except:
            pass

        print("\nFINAL COMPARISON RESULTS")
        print_table()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
