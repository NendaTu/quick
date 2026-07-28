"""
1. Summary: Backtesting execution coordinator with multi-variant and timeline support.
2. Description: Runs historical backtests for a list of strategies or strategy families sharing capital in a single loop. Handles date boundaries, database warmups, asset discovery, stream logging redirection, contract specs caching, and graceful finalizations.
3. Context: Relies on config.py, database.py, simulator.py, tools/logger.py, and tools/publisher.py.
"""
import sys
import os
import signal
try:
    signal.signal(signal.SIGINT, signal.default_int_handler)
except Exception:
    pass

from tools.logger import setup_console_tee, Tee
stdout_tee, stderr_tee = setup_console_tee()

import asyncio
import math
import random
import logging
import time
import importlib
import importlib.util
import inspect
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# Ensure project root is in path
sys.path.append(os.getcwd())

import config
from database import Database
from bitget_client import BitGetClient, RateLimiter
from engine.simulation import SimulationEngine
from config import BTC_SYMBOL, AVAILABLE_TIMEFRAMES, ASSETS_COUNT, ASSET_OMITTED, MAX_START_DATE, MAX_END_DATE, TF_SECONDS
from tools.trading_utils import calculate_fees, calculate_pnl, calculate_net_pnl, calculate_position_size

# --- Backtest Settings ---
PROXIMITY_LIMIT = 5
RESET_PROXIMITY_ON_REPEAT = True
DIRECTION_MODE = "strict" # "strict" or "open"

# --- Backtest Core Toggles ---
USE_PORTFOLIO_MODE = True # If True, simulates concurrent capital-sharing portfolio mode. If False, runs isolated single-asset mode.

# Set to [] to enable automatic discovery by volume
DEFAULT_ASSETS = [] # for quick tests, use all or some of: "ETHUSDT", "HBARUSDT", "UNIUSDT", "GRTUSDT", "SOLUSDT", "ENAUSDT", "SUIUSDT", "DOGEUSDT"
DEFAULT_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1H"]

# Default to Dec 2025 - June 2026 as requested by user
DEFAULT_START_DATE = datetime(2026, 3, 1, tzinfo=timezone.utc)
DEFAULT_END_DATE = datetime(2026, 6, 1, tzinfo=timezone.utc)

START_DATE = DEFAULT_START_DATE
END_DATE = DEFAULT_END_DATE

# [TECH-001] Use centralized logging
from tools.logger import setup_logging
setup_logging(level=logging.INFO)

log = logging.getLogger("backtest")

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

        # Calculate moving average rate to stabilize ETA
        current_rate = self.current / elapsed if elapsed > 0 else 0
        if not hasattr(self, "_last_rate"): self._last_rate = current_rate
        self._last_rate = (self._last_rate * 0.9) + (current_rate * 0.1) # EMA smoothing

        eta = (self.total - self.current) / self._last_rate if self._last_rate > 0 else 0

        # Format: ASSET: TF (PCT% / ETA s)
        msg = f"\r{self.label} ({int(pct)}% / {int(eta)}s) Elapsed: {int(elapsed)}s"

        # Clear tail of previous longer lines
        padding = max(0, self._last_line_len - len(msg))
        full_msg = msg + (" " * padding)

        sys.stdout.write(full_msg)
        sys.stdout.flush()
        self._last_line_len = len(msg)

        if self.current >= self.total:
            print()

async def discover_assets(client: BitGetClient) -> List[str]:
    """Discover top assets by volume, identical to main.py logic."""
    log.info(f"Discovering top {ASSETS_COUNT} assets by volume...")
    tickers = await client.get_tickers()
    # Sort by usdtVolume descending
    sorted_tickers = sorted(tickers, key=lambda x: float(x.get("usdtVolume", 0)), reverse=True)

    discovered = []
    for t in sorted_tickers:
        sym = t["symbol"]
        if sym.endswith("USDT") and sym not in ASSET_OMITTED:
            # Exclude known stables
            if sym.replace("USDT", "") in ["USDC", "DAI", "BUSD", "EUR", "GBP"]:
                continue
            discovered.append(sym)
            if len(discovered) >= ASSETS_COUNT:
                break
    return discovered

async def download_historical_data(client: BitGetClient, db: Database, assets: List[str], timeframes: List[str], silent: bool = False, chain=None):
    """
    [TECH-001] Accelerated historical data acquisition using concurrency and a global progress bar.
    Includes a 14-day warm-up buffer if indicators are required.
    """
    target_tfs = timeframes
    if not silent:
        log.debug(f"Acquiring historical data for {target_tfs}...")

    session_start = time.time()

    # Determine if warm-up is required
    requires_warmup = False
    if chain:
        for segment in chain.segments:
            for wrapper in segment:
                strategies = wrapper.instance if isinstance(wrapper.instance, list) else [wrapper.instance]
                for strat in strategies:
                    bypass = getattr(strat, "params", {}).get("bypass_external_filters", True)
                    is_indicator_heavy = any(x in getattr(strat, "name", "").lower() for x in ["sweep", "scalper", "fvg"])
                    if not bypass or is_indicator_heavy:
                        requires_warmup = True; break
                if requires_warmup: break
            if requires_warmup: break

    dl_start_ts = START_DATE.timestamp()
    if requires_warmup:
        dl_start_ts -= (86400 * 14) # 14 days warm-up
        log.info(f"Warm-up buffer enabled (14 days). Starting acquisition from {datetime.fromtimestamp(dl_start_ts, tz=timezone.utc)}. Elapsed: {int(time.time() - session_start)}s")

    # 1. First Pass: Identify all gaps to build a global progress bar
    all_gaps = []
    total_candles = 0
    skipped_count = 0
    for asset in assets:
        for tf in target_tfs:
            gaps = db.get_data_gaps(asset, tf, dl_start_ts, END_DATE.timestamp())
            if gaps:
                all_gaps.append((asset, tf, gaps))
                total_candles += sum((g[1] - g[0] + TF_SECONDS[tf]) for g in gaps) / TF_SECONDS[tf]
            else:
                skipped_count += 1

    if not all_gaps:
        log.info(f"Historical data complete for all {len(assets)} assets. Elapsed: {int(time.time() - session_start)}s")
        return

    # [TECH-001] Unified Global Progress Bar
    if skipped_count > 0:
        log.info(f"Acquisition: Skipping {skipped_count} segments (already complete).")

    global_progress = Progress(int(total_candles), label=f"Acquisition: {len(assets)} Assets")
    assets_completed = 0

    from engine.exchanges.bitget import BitgetExchange
    semaphore = asyncio.Semaphore(BitgetExchange.DEFAULT_CONCURRENCY)
    from tools.downloader import RateLimiter
    limiter = RateLimiter(BitgetExchange.DEFAULT_RPS)

    async def download_asset_tf_gap(asset, tf, gaps):
        nonlocal assets_completed

        # [REPAIR-20260702] Use optimized batch fetching with global semaphore
        async def fetch_chunk(chunk_end_ms, target_start_ms, target_end_ms):
            async with semaphore:
                try:
                    await limiter.wait()
                    # Single source of truth for request and backoff
                    response = await client.request("GET", "/api/v2/mix/market/history-candles", params={
                        "symbol": asset, "productType": "usdt-futures", "granularity": tf,
                        "endTime": str(chunk_end_ms), "limit": "200"
                    })
                    if response.get("code") == "00000":
                        data = response.get("data", [])
                        if not data: return -1 # Beginning of history
                        valid_count = 0
                        for c in data:
                            ts_ms = int(c[0])
                            if ts_ms < target_start_ms: continue
                            if ts_ms > target_end_ms: continue
                            db.save_candle(asset, tf, ts_ms / 1000, float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5]))
                            valid_count += 1
                        global_progress.update(valid_count)
                        return valid_count
                except Exception as e:
                    log.error(f"Error in backtest fetch_chunk {asset} {tf}: {e}")
                return 0

        for gap_start, gap_end in gaps:
            target_start_ms = int(gap_start * 1000)
            target_end_ms = int(gap_end * 1000)

            total_gap_ms = target_end_ms - target_start_ms
            chunk_ms = 200 * TF_SECONDS[tf] * 1000
            num_chunks = math.ceil(total_gap_ms / chunk_ms)

            # [REPAIR-20260702] Sequential chunking to prevent freeze
            for i in range(num_chunks):
                chunk_end_ms = target_end_ms - (i * chunk_ms)
                if chunk_end_ms <= target_start_ms: break
                res = await fetch_chunk(chunk_end_ms, target_start_ms, target_end_ms)
                if res == -1: break # Stop if beginning of history reached

    tasks = [download_asset_tf_gap(a, t, g) for a, t, g in all_gaps]
    await asyncio.gather(*tasks)
    print() # Final newline for global progress

def find_strategy_file(query: str) -> Optional[str]:
    # [TECH-001] Support directory-based discovery (Families)
    if query == "strategies":
        return "strategies"

    potential_dir = os.path.join("strategies", query)
    if os.path.isdir(potential_dir):
        return potential_dir

    # 1. Search strategies/ recursively
    strategy_matches = []
    for root, dirs, files in os.walk("strategies"):
        for file in files:
            if file.endswith(".py") and not file.startswith("__") and "base_strategy" not in file:
                rel_path = os.path.relpath(os.path.join(root, file), "strategies")
                clean_path = rel_path.replace("\\", "/").replace(".py", "")

                # Exact match (e.g. "sweeps/killzone/killzone_sweep.1.mustafa")
                if clean_path.lower() == query.lower():
                    return os.path.join(root, file)

                # Partial match (e.g. "killzone_sweep")
                if query.lower() in clean_path.lower():
                    strategy_matches.append(os.path.join(root, file))

    if len(strategy_matches) == 1:
        return strategy_matches[0]

    # 2. Recursively search ta/
    matches = strategy_matches # Merge strategy matches into the overall pool

    # Handle the singular/plural mapping (candle -> candles)
    mapping = {"candle": "candles", "pattern": "patterns", "indicator": "indicators"}
    mapped_query = query
    for sing, plur in mapping.items():
        if query.startswith(f"{sing}/"):
            mapped_query = query.replace(f"{sing}/", f"{plur}/", 1)
            break

    for root, dirs, files in os.walk("ta"):
        for file in files:
            if file.endswith(".py") and not file.startswith("__"):
                rel_path = os.path.relpath(os.path.join(root, file), "ta")
                # Normalize separators
                rel_path_norm = rel_path.replace("\\", "/")
                # Remove .py
                clean_path = rel_path_norm[:-3]

                # Check exact match or partial match
                if clean_path.lower() == mapped_query.lower():
                    return os.path.join(root, file)

                if query.lower() in clean_path.lower():
                    matches.append(os.path.join(root, file))

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        # Check if we are in an interactive terminal
        if not sys.stdin.isatty():
            print(f"\nError: Multiple strategies found for '{query}', but terminal is non-interactive.", file=sys.stderr)
            for m in matches:
                print(f"  - {m}", file=sys.stderr)
            return None

        print(f"\nMultiple strategies found matching '{query}':")
        for i, m in enumerate(matches):
            print(f"{i+1}) {m}")
        try:
            choice = input("Select a strategy (number) or press Enter to cancel: ")
            idx = int(choice) - 1
            if 0 <= idx < len(matches):
                return matches[idx]
        except (EOFError, ValueError, KeyboardInterrupt):
            print("\nSelection cancelled.")
            pass
    return None

class StrategyWrapper:
    def __init__(self, path: str, params: List[str] = None, ignore_direction: bool = False, is_flipped: bool = False, simulator=None, overrides=None):
        self.path = path
        self.params = params or []
        self.ignore_direction = ignore_direction
        self.is_flipped = is_flipped
        self.simulator = simulator
        self.overrides = overrides or {}
        self.instance = self._load_strategy(path)

    def _load_strategy(self, path):
        # [TECH-001] Use the enhanced load_strategy from main.py
        from main import load_strategy
        # Extract relative path if inside strategies/
        rel_path = path
        if path.startswith("strategies/"):
             rel_path = path[11:]
        if rel_path.endswith(".py"):
             rel_path = rel_path[:-3]

        model = None
        if self.simulator and hasattr(self.simulator, "engine") and self.simulator.engine:
            model = self.simulator.engine.model

        res = load_strategy(rel_path, simulator=self.simulator, model=model, overrides=self.overrides)
        if res is not None:
            return res

        # Fallback for simple pattern/indicator modules under ta/ or anywhere else
        try:
            spec = importlib.util.spec_from_file_location("strategy_mod", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
        except Exception as e:
            log.error(f"Error falling back to module loader for {path}: {e}")
        return None

    def get_signal(self, ohlcv, tf, symbol=None):
        """
        [TECH-001] Handle both single strategy instances and Families (lists).
        """
        if isinstance(self.instance, list):
            # Family: In backtest.py, we only return the FIRST strategy signal for the chain check.
            # TRUE multi-strategy execution happens in the run_backtest simulation loop
            # where Engine.strategies is processed.
            if not self.instance: return None
            target = self.instance[0]
        else:
            target = self.instance

        if target is None:
            return None

        if hasattr(target, "get_entry_signal"):
            market_data = {
                "symbol": symbol or "BACKTEST",
                "book": type('obj', (object,), {'best_bid': ohlcv[-1]['c'], 'best_ask': ohlcv[-1]['c']}),
                "equity": config.INITIAL_EQUITY,
                "features": None # Simulator will be used if None
            }
            return target.get_entry_signal(market_data)

        return target.get_signal(ohlcv, tf, params=self.params)

class ConfluenceChain:
    def __init__(self, segments: List[List[StrategyWrapper]]):
        """
        segments: List of simultaneous groups.
        Example: [[A, B], [C], [D, E]] represents (A+B) > C > (D+E)
        """
        self.segments = segments
        self.current_segment_idx = 0
        self.proximity_timer = 0
        self.root_direction = None # Establish by the first segment
        self.chain_active = False

    def reset(self):
        self.current_segment_idx = 0
        self.proximity_timer = 0
        self.root_direction = None
        self.chain_active = False

    def check(self, ohlcv, tf, symbol=None):
        if not self.segments:
            return None

        # 1. Evaluate current segment
        current_segment = self.segments[self.current_segment_idx]
        segment_results = [s.get_signal(ohlcv, tf, symbol=symbol) for s in current_segment]

        # All must signal in the same direction (if not ignored)
        direction = None
        all_match = True

        for i, res in enumerate(segment_results):
            if res is None:
                all_match = False
                break

            sig_dir = res["side"]
            if sig_dir == "both":
                continue # Filter strategy, matches any direction

            if not current_segment[i].ignore_direction and DIRECTION_MODE == "strict":
                if direction is None:
                    direction = sig_dir
                elif direction != sig_dir:
                    all_match = False
                    break
            elif direction is None:
                direction = sig_dir

        # 2. Handle Segment Result
        if all_match:
            # establish root direction on first match
            if self.current_segment_idx == 0:
                target_direction = direction
            else:
                # Determine target direction based on root
                # By default (strict), we match root.
                target_direction = self.root_direction

                # Check if any item in this segment is flipped
                # (For simultaneous groups, they should ideally all be flipped or none,
                # but we'll respect the first item's flip state for the group)
                if current_segment[0].is_flipped:
                    target_direction = "sell" if self.root_direction == "buy" else "buy"
                    # log.debug(f"Segment {self.current_segment_idx} Flipped: target={target_direction} (root={self.root_direction})")

            valid_transition = True
            if DIRECTION_MODE == "strict":
                # Check if this segment's wrappers allow ignoring direction
                should_match = any(not s.ignore_direction for s in current_segment)
                if should_match and direction != target_direction:
                    valid_transition = False

            if valid_transition:
                # Progress the chain
                if self.current_segment_idx == 0:
                    self.chain_active = True

                # Establish or maintain root direction from directional signals
                if direction is not None and self.root_direction is None:
                    self.root_direction = direction

                self.proximity_timer = PROXIMITY_LIMIT

                # If this was the last segment, return the result
                if self.current_segment_idx == len(self.segments) - 1:
                    final_res = segment_results[-1] # Anchor is the last item
                    self.reset()
                    return final_res

                self.current_segment_idx += 1
                return None

        # 3. Handle Timer / Reset
        if self.chain_active:
            # If the FIRST segment repeats, reset proximity timer if configured
            if RESET_PROXIMITY_ON_REPEAT:
                first_segment = self.segments[0]
                first_results = [s.get_signal(ohlcv, tf) for s in first_segment]
                if all(r is not None for r in first_results):
                    # Check direction for repeat reset
                    first_dir = first_results[0]["side"]
                    if DIRECTION_MODE == "open" or first_dir == self.root_direction:
                        self.proximity_timer = PROXIMITY_LIMIT
                        # Also reset to waiting for segment 1 (index 1)
                        self.current_segment_idx = 1

            self.proximity_timer -= 1
            if self.proximity_timer < 0:
                self.reset()

        return None

def parse_confluence_command(command: str):
    """
    Parses a string like "A + B -> C -> D + E" or "A B -> C" into segments.
    Also handles "~" and "open".
    """
    global DIRECTION_MODE
    if command.endswith(" open"):
        DIRECTION_MODE = "open"
        command = command[:-5].strip()

    # Split by "->" for sequential (to avoid shell redirection conflict with ">")
    steps = [s.strip() for s in command.split("->")]

    segments = []
    for step in steps:
        step = step.strip()
        if not step: continue

        # Check if the entire segment is flipped: (A + B)
        seg_flipped = False
        if step.startswith("(") and step.endswith(")"):
            seg_flipped = True
            step = step[1:-1].strip()

        # Split strictly by "+" for simultaneous
        parts = [p.strip() for p in step.split("+")]

        wrappers = []
        for p in parts:
            if not p: continue

            ignore_dir = False
            if p.endswith("~"):
                ignore_dir = True
                p = p[:-1].strip()

            is_flipped = seg_flipped
            if p.startswith("(") and p.endswith(")"):
                is_flipped = True
                p = p[1:-1].strip()

            # Resolution logic
            # Extract query and params (space separated)
            bits = p.split()
            query = bits[0]
            params = bits[1:]

            strat_path = find_strategy_file(query)
            if not strat_path:
                raise ValueError(f"Strategy {query} not found")

            wrappers.append(StrategyWrapper(strat_path, params=params, ignore_direction=ignore_dir, is_flipped=is_flipped))

        segments.append(wrappers)

    return ConfluenceChain(segments)

async def run_backtest(chain, db: Database, client: BitGetClient, asset: str, tf: str, overrides: Dict = None):
    # BT-002: Reset config to default before each asset/tf run to ensure no leakage from strategies
    import importlib, config
    importlib.reload(config)

    if overrides:
        for k, v in overrides.items():
            if hasattr(config, k):
                setattr(config, k, v)

    # Clear strategy state for this asset to ensure clean run
    if db:
        for segment in chain.segments:
            for wrapper in segment:
                strats = wrapper.instance if isinstance(wrapper.instance, list) else [wrapper.instance]
                for s in strats:
                    strat_id = getattr(s, "strategy_id", None) or getattr(s, "name", "")
                    if strat_id:
                        db.connection.execute("DELETE FROM strategy_state WHERE strategy_id = ? AND key LIKE ?", (strat_id, f"{asset}%"))
                        db.connection.commit()

    # USE THE UNIFIED SIMULATION ENGINE FORCED TO PAPER MODE FOR BACKTESTING
    from engine.core import Engine
    engine = Engine(use_db=False, mode="paper", config_overrides=overrides)
    engine.start_time = time.time()
    peak_equity = config.INITIAL_EQUITY

    sim = engine.exchange
    sim.db = db
    sim.is_backtest = True

    # Load contract specs with local JSON cache to prevent network freezes [REPAIR]
    import json
    specs_cache_path = "docs/temp/contract_specs_cache.json"
    specs = []
    if os.path.exists(specs_cache_path):
        try:
            with open(specs_cache_path, "r") as f:
                specs = json.load(f)
            log.info("Loaded contract specifications from local cache.")
        except Exception as cache_err:
            log.warning(f"Failed to read local contract specs cache: {cache_err}")

    if not specs:
        try:
            log.info("Fetching contract specifications from Bitget API...")
            specs = await client.get_symbols()
            if specs:
                os.makedirs(os.path.dirname(specs_cache_path), exist_ok=True)
                with open(specs_cache_path, "w") as f:
                    json.dump(specs, f)
        except Exception as api_err:
            log.error(f"Failed to fetch contract specs from API: {api_err}")
            # Robust fallback specs if both cache and API fail
            specs = [{"symbol": asset, "pricePlace": "2", "volumePlace": "3", "minTradeUSDT": "5"} for asset in assets]

    spec_map = {s['symbol']: s for s in specs}
    sim.contract_specs = spec_map
    sim.leverage_limits = {s: float(spec_map[s].get('maxLever', 20)) for s in spec_map if s in [asset, BTC_SYMBOL]}
    engine.leverage_limits = sim.leverage_limits
    sim.discovered_assets = [asset]
    sim.ready_assets = {asset, BTC_SYMBOL} # Mark as ready for backtest loop

    from orderbook import SimulatedOrderBook, OrderBook
    for sym in [asset, BTC_SYMBOL]:
        sim.books[sym] = SimulatedOrderBook(sym, 1.0)
        engine.books[sym] = OrderBook(sym)

    # Load candles from DB within the specified range
    candles = db.get_candles_in_range(asset, tf, START_DATE.timestamp(), END_DATE.timestamp())
    if not candles:
        return None

    if len(candles) < 10:
        return None

    # Inject relevant timeframes for this asset and BTC for confluence
    history_sec = 86400 * 14 # 14 days history for indicators (especially for 4H ATR)
    asset_history = {}

    # Discovery of relevant timeframes from the strategy chain
    relevant_tfs = get_required_timeframes(chain)
    if tf not in relevant_tfs:
        relevant_tfs.append(tf)
    log.info(f"Backtest using timeframes: {relevant_tfs}")

    for sym in [asset, BTC_SYMBOL]:
        sim.ohlcv[sym] = {t: [] for t in relevant_tfs}
        sim.confluence_history[sym] = {t: [] for t in ["15m", "1H", "4H", "1D", "1W"]}
        asset_history[sym] = {}
        for t in relevant_tfs:
            c_data = db.get_candles_in_range(sym, t, START_DATE.timestamp() - history_sec, END_DATE.timestamp())
            data = [{"ts": ts, "o": o, "h": h, "l": l, "c": cl, "v": v} for ts, o, h, l, cl, v in c_data]
            asset_history[sym][t] = data

            # Pre-populate simulator with history UP TO START_DATE (fully closed candles only)
            for c in data:
                if c['ts'] + TF_SECONDS[t] <= START_DATE.timestamp():
                    sim.ohlcv[sym][t].append(c)
                    if t in sim.confluence_history[sym]:
                        sim.confluence_history[sym][t].append(c['c'])
                else:
                    break

    # Find the starting index for our loop (first candle >= START_DATE)
    full_history = asset_history[asset][tf]
    start_idx = 0
    for i, c in enumerate(full_history):
        if c['ts'] >= START_DATE.timestamp():
            start_idx = i
            break

    progress = Progress(len(full_history) - start_idx, label=f"BT {asset}: {tf}")
    chain.reset()

    # [TECH-001] Load Strategy Family into Engine with FRESH instances and simulator linked
    engine.strategies = []
    for segment in chain.segments:
        for wrapper in segment:
            wrapper.simulator = sim
            # Re-load instance with fresh state and simulator linked
            wrapper.instance = wrapper._load_strategy(wrapper.path)

            # Re-apply overrides if any
            if wrapper.overrides:
                strats = wrapper.instance if isinstance(wrapper.instance, list) else [wrapper.instance]
                for s in strats:
                    for k, v in wrapper.overrides.items():
                        if hasattr(s, "params") and k in s.params:
                            s.params[k] = v

            if isinstance(wrapper.instance, list):
                engine.strategies.extend(wrapper.instance)
            else:
                engine.strategies.append(wrapper.instance)

    log.info(f"Engine initialized with {len(engine.strategies)} strategies.")

    for s in engine.strategies:
        sid = getattr(s, "strategy_id", getattr(s, "name", "unknown"))
        if sid not in engine.strategy_stats:
            engine.strategy_stats[sid] = {
                "pnl": 0.0,
                "total_trades": 0,
                "buy_wins": 0,
                "buy_losses": 0,
                "sell_wins": 0,
                "sell_losses": 0,
                "tp_wins": 0,
                "be_wins": 0
            }

    # Track pointers into history for each timeframe/symbol to avoid re-scanning
    pointers = {sym: {t: 0 for t in relevant_tfs} for sym in [asset, BTC_SYMBOL]}
    # Advance pointers to where we pre-populated
    for sym in [asset, BTC_SYMBOL]:
        for t in relevant_tfs:
            while pointers[sym][t] < len(asset_history[sym][t]) and asset_history[sym][t][pointers[sym][t]]['ts'] + TF_SECONDS[t] <= START_DATE.timestamp():
                pointers[sym][t] += 1

    # Remove artificial latency for backtests
    sim.latency_simulation = False

    overrides_dict = overrides or {}
    hb_interval = overrides_dict.get("heartbeat_interval", 30)
    last_hb_time = 0

    try:
        # Simulation Loop using unified engine
        for i in range(start_idx, len(full_history)):
            c = full_history[i]
            import tools.logger
            tools.logger.VIRTUAL_TIME = c['ts']

            # Periodic Heartbeat in Backtest Console Output based on real elapsed time
            now_real = time.time()
            if now_real - last_hb_time >= hb_interval:
                from tools.publisher import ConsolePublisher
                wr = (engine.winning_trades / engine.total_trades * 100) if engine.total_trades > 0 else 0
                pr_val = engine.profit_ratio
                ConsolePublisher.publish_heartbeat(c['ts'], engine.equity, engine.total_trades, wr, pr_val, len(engine.open_positions), engine.session_signals)
                last_hb_time = now_real

            o, h, l, cl = c['o'], c['h'], c['l'], c['c']

            # [PERF-004] Skip sub-candle simulation if idle to boost speed
            intra_candle_prices = [o, h, l, cl]
            if not sim.positions and not sim.pending_orders:
                intra_candle_prices = [cl] # Only simulate close if idle

            # [PERF-001] Update simulator's OHLCV with sliding window
            sim.ohlcv[asset][tf].append(c)
            if len(sim.ohlcv[asset][tf]) > 1000: sim.ohlcv[asset][tf].pop(0)

            if tf in sim.confluence_history[asset]:
                sim.confluence_history[asset][tf].append(cl)
                if len(sim.confluence_history[asset][tf]) > 1000: sim.confluence_history[asset][tf].pop(0)

            # [BT-001] Simulate Price Action
            for price in intra_candle_prices:
                sim.last_price[asset] = price
                if asset in sim.books:
                    sim.books[asset].mid_price = price
                    sim.books[asset]._regenerate()

                    # Sync Engine's shadow books for tradability checks
                    if asset in engine.books:
                        engine.books[asset].bids = list(sim.books[asset].bids)
                        engine.books[asset].asks = list(sim.books[asset].asks)
                        engine.books[asset].timestamp = c['ts']

                # [PERF-002] Order processing is only needed if we have positions or pending orders
                if sim.positions or sim.pending_orders:
                    await sim._process_orders()

            # 2. Check for entry signal
            if len(sim.ohlcv[asset][tf]) >= 2:
                # Synchronize BTC and other timeframes to the current timestamp
                current_ts = c['ts']
                for sym in [asset, BTC_SYMBOL]:
                    for t in relevant_tfs:
                        if sym == asset and t == tf: continue

                        # [PERF-003] Only sync history when needed (fully closed/completed bars only)
                        while pointers[sym][t] < len(asset_history[sym][t]):
                            new_c = asset_history[sym][t][pointers[sym][t]]
                            # Ensure the bar of timeframe t has fully closed before the current timestamp (current_ts)
                            if new_c['ts'] + TF_SECONDS[t] <= current_ts:
                                sim.ohlcv[sym][t].append(new_c)
                                if len(sim.ohlcv[sym][t]) > 1000: sim.ohlcv[sym][t].pop(0)

                                if t in sim.confluence_history[sym]:
                                    sim.confluence_history[sym][t].append(new_c['c'])
                                    if len(sim.confluence_history[sym][t]) > 1000: sim.confluence_history[sym][t].pop(0)

                                pointers[sym][t] += 1
                            else:
                                break

                # [TECH-001] Support Strategy Families in Backtests
                active_signals = []
                if engine.strategies:
                    # Mock market_data for class-based strategies
                    market_data = {
                        "symbol": asset,
                        "book": sim.books[asset],
                        "equity": sim.equity,
                        "features": None # Simulator will be used if None
                    }
                    for strat in engine.strategies:
                        # [TECH-001] AUTHENTICITY GUARD: Check if this specific strategy is ready
                        if hasattr(strat, "is_ready") and not strat.is_ready(asset):
                            continue

                        if hasattr(strat, "get_entry_signal"):
                            # Ensure strategy has access to current simulation state
                            if hasattr(strat, "model") and hasattr(strat.model, "simulator"):
                                strat.model.simulator = sim

                            sig = strat.get_entry_signal(market_data)
                            if sig:
                                engine.session_signals += 1
                                sig["strategy_id"] = sig.get("strategy_id") or getattr(strat, "strategy_id", getattr(strat, "name", "unknown"))
                                active_signals.append(sig)
                else:
                    # Legacy Confluence Chain
                    signal = chain.check(sim.ohlcv[asset][tf], tf, symbol=asset)
                    if signal:
                        engine.session_signals += 1
                        signal["strategy_id"] = "chain"
                        active_signals.append(signal)

                for signal in active_signals:
                    # 1. Scoring Confluence Gating Check
                    feat = sim.get_features(asset)
                    if not feat:
                        continue

                    from ta.scoring import ScoringEngine
                    se = ScoringEngine()
                    strategy_id = signal.get("strategy_id", "unknown")

                    if strategy_id == "model":
                        scoring_result = se.evaluate(feat, side=signal["side"], config_context=config, dynamic_weights=engine.model.weights)
                    else:
                        scoring_result = se.evaluate(feat, side=signal["side"], config_context=config)

                    # Always write to the complete signals log file
                    engine._write_signals_log(asset, signal["side"], strategy_id, scoring_result)

                    if scoring_result["decision"] == "REJECTED":
                        continue

                    # [TECH-001] Collision check for backtest loop
                    if not engine._asset_is_tradable(asset, signal["side"], features=feat, signal=signal):
                        continue

                    # Place trade via unified engine
                    kwargs = signal.copy()
                    for key in ["symbol", "side", "qty", "entry_price", "stop_price", "exit_price", "tp_price", "strategy_id"]:
                        kwargs.pop(key, None)

                    res = sim.place_trade_oco(
                        asset, signal["side"], signal.get("qty", 0),
                        signal["entry_price"], signal["stop_price"], signal.get("exit_price") or signal.get("tp_price"),
                        features=feat,
                        strategy_id=signal.get("strategy_id"),
                        **kwargs
                    )

                    if res and res.get("code") == "00000":
                        engine._write_metrics_log(asset, signal["side"], strategy_id, scoring_result)

            # Enforce protective safety limit checks (Drawdown, ROI, Max Trades, Duration)
            if sim.equity > peak_equity:
                peak_equity = sim.equity

            # 1. Drawdown Limit
            if peak_equity > 0 and sim.equity <= config.DRAWDOWN_LIMIT * peak_equity:
                log.critical(f"DRAWDOWN LIMIT HIT: equity={sim.equity:.2f}, peak={peak_equity:.2f} | Stopping Backtest.")
                break

            # 2. ROI Limit
            roi = (sim.equity / config.INITIAL_EQUITY - 1)
            if roi >= config.TOTAL_ROI_LIMIT:
                log.critical(f"ROI TARGET REACHED: equity={sim.equity:.2f}, ROI={roi*100:.1f}% | Stopping Backtest.")
                break

            # 3. Trade Count Limit
            if engine.total_trades >= config.MAX_TRADES_LIMIT:
                log.critical(f"TRADE LIMIT REACHED: {engine.total_trades} trades | Stopping Backtest.")
                break

            # 4. Duration Limit
            elapsed_real = time.time() - engine.start_time
            if elapsed_real >= config.MAX_DURATION:
                log.critical(f"DURATION LIMIT REACHED: {elapsed_real:.0f}s (Real) | Stopping Backtest.")
                break

            progress.update(1)
    except KeyboardInterrupt:
        log.warning(f"\n[CTRL+C] Backtest for {asset} interrupted by user. Finalizing partial results...")
        if engine.open_positions:
            print("\n" + "="*60)
            print("CURRENT OPEN POSITIONS AT INTERRUPTION:")
            print("-" * 60)
            for pos_key, p in engine.open_positions.items():
                print(f"  - {pos_key:15} | Side: {p['side'].upper():4} | Qty: {p['qty']:8.3f} | Entry: {p['entry']:10.8f} | Margin: {p['margin']:.2f}")
            print("="*60 + "\n")

    roi = (sim.equity / config.INITIAL_EQUITY - 1) * 100

    # Capture results from Engine
    ss = engine.asset_stats.get(asset, {"buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0, "pnl": 0.0, "buy_pnl": 0.0, "sell_pnl": 0.0})
    side_stats = {
        "long": {"trades": ss["buy_wins"] + ss["buy_losses"], "wins": ss["buy_wins"], "pnl": ss["buy_pnl"]},
        "short": {"trades": ss["sell_wins"] + ss["sell_losses"], "wins": ss["sell_wins"], "pnl": ss["sell_pnl"]}
    }

    # Calculate ROE based on actual cumulative margin
    total_margin = ss.get("total_margin", 0)
    avg_roe = (ss["pnl"] / total_margin * 100) if total_margin > 0 else 0

    import tools.logger
    tools.logger.VIRTUAL_TIME = None

    return {
        "asset": asset,
        "tf": tf,
        "roe": avg_roe,
        "pnl": ss["pnl"],
        "roi": roi,
        "win_rate": (engine.winning_trades / engine.total_trades * 100) if engine.total_trades > 0 else 0,
        "trades": engine.total_trades,
        "equity": sim.equity,
        "side_stats": side_stats,
        "strategy_stats": engine.strategy_stats, # [TECH-001] Include strategy breakdown
        "no_data": False
    }

async def run_backtest_portfolio(chain, db: Database, client: BitGetClient, assets: List[str], tf: str, overrides: Dict = None) -> List[Dict]:
    import importlib, config
    importlib.reload(config)

    if overrides:
        for k, v in overrides.items():
            if hasattr(config, k):
                setattr(config, k, v)

    # Clear strategy state for all assets to ensure clean run
    if db:
        for asset in assets:
            for segment in chain.segments:
                for wrapper in segment:
                    strats = wrapper.instance if isinstance(wrapper.instance, list) else [wrapper.instance]
                    for s in strats:
                        strat_id = getattr(s, "strategy_id", None) or getattr(s, "name", "")
                        if strat_id:
                            db.connection.execute("DELETE FROM strategy_state WHERE strategy_id = ? AND key LIKE ?", (strat_id, f"{asset}%"))
                            db.connection.commit()

    # Load candles for all assets from DB within the specified range
    asset_candles = {}
    for asset in assets:
        candles = db.get_candles_in_range(asset, tf, START_DATE.timestamp(), END_DATE.timestamp())
        if candles:
            asset_candles[asset] = [{"ts": ts, "o": o, "h": h, "l": l, "c": cl, "v": v} for ts, o, h, l, cl, v in candles]

    # Find all unique timestamps across all assets to build the master timeline
    all_timestamps = set()
    for asset, candles in asset_candles.items():
        for c in candles:
            all_timestamps.add(c["ts"])

    timeline = sorted(list(all_timestamps))

    if not timeline:
        return []

    # Map candles by timestamp for O(1) fast lookup
    candle_by_ts = {asset: {c["ts"]: c for c in candles} for asset, candles in asset_candles.items()}

    # USE THE UNIFIED SIMULATION ENGINE FORCED TO PAPER MODE FOR BACKTESTING
    from engine.core import Engine
    engine = Engine(use_db=False, mode="paper", config_overrides=overrides)
    engine.start_time = time.time()
    peak_equity = config.INITIAL_EQUITY

    sim = engine.exchange
    sim.db = db
    sim.is_backtest = True

    # Load contract specs with local JSON cache to prevent network freezes [REPAIR]
    import json
    specs_cache_path = "docs/temp/contract_specs_cache.json"
    specs = []
    if os.path.exists(specs_cache_path):
        try:
            with open(specs_cache_path, "r") as f:
                specs = json.load(f)
            log.info("Loaded contract specifications from local cache.")
        except Exception as cache_err:
            log.warning(f"Failed to read local contract specs cache: {cache_err}")

    if not specs:
        try:
            log.info("Fetching contract specifications from Bitget API...")
            specs = await client.get_symbols()
            if specs:
                os.makedirs(os.path.dirname(specs_cache_path), exist_ok=True)
                with open(specs_cache_path, "w") as f:
                    json.dump(specs, f)
        except Exception as api_err:
            log.error(f"Failed to fetch contract specs from API: {api_err}")
            # Robust fallback specs if both cache and API fail
            specs = [{"symbol": asset, "pricePlace": "2", "volumePlace": "3", "minTradeUSDT": "5"} for asset in assets]

    spec_map = {s['symbol']: s for s in specs}
    sim.contract_specs = spec_map
    sim.leverage_limits = {s: float(spec_map[s].get('maxLever', 20)) for s in spec_map if s in assets + [BTC_SYMBOL]}
    engine.leverage_limits = sim.leverage_limits
    sim.discovered_assets = assets
    sim.ready_assets = set(assets + [BTC_SYMBOL]) # Mark as ready for backtest loop

    from orderbook import SimulatedOrderBook, OrderBook
    for sym in assets + [BTC_SYMBOL]:
        sim.books[sym] = SimulatedOrderBook(sym, 1.0)
        engine.books[sym] = OrderBook(sym)

    # Inject relevant timeframes for all assets and BTC for confluence
    history_sec = 86400 * 14 # 14 days history for indicators
    asset_history = {}

    # Discovery of relevant timeframes from the strategy chain
    relevant_tfs = get_required_timeframes(chain)
    if tf not in relevant_tfs:
        relevant_tfs.append(tf)
    log.info(f"Backtest using timeframes: {relevant_tfs}")

    for sym in assets + [BTC_SYMBOL]:
        sim.ohlcv[sym] = {t: [] for t in relevant_tfs}
        sim.confluence_history[sym] = {t: [] for t in ["15m", "1H", "4H", "1D", "1W"]}
        asset_history[sym] = {}
        for t in relevant_tfs:
            c_data = db.get_candles_in_range(sym, t, START_DATE.timestamp() - history_sec, END_DATE.timestamp())
            data = [{"ts": ts, "o": o, "h": h, "l": l, "c": cl, "v": v} for ts, o, h, l, cl, v in c_data]
            asset_history[sym][t] = data

            # Pre-populate simulator with history UP TO START_DATE
            for c in data:
                if c['ts'] + TF_SECONDS[t] <= START_DATE.timestamp():
                    sim.ohlcv[sym][t].append(c)
                    if t in sim.confluence_history[sym]:
                        sim.confluence_history[sym][t].append(c['c'])
                else:
                    break

    # [TECH-001] Load Strategy Family into Engine with FRESH instances and simulator linked
    engine.strategies = []
    for segment in chain.segments:
        for wrapper in segment:
            wrapper.simulator = sim
            # Re-load instance with fresh state and simulator linked
            wrapper.instance = wrapper._load_strategy(wrapper.path)

            # Re-apply overrides if any
            if wrapper.overrides:
                strats = wrapper.instance if isinstance(wrapper.instance, list) else [wrapper.instance]
                for s in strats:
                    for k, v in wrapper.overrides.items():
                        if hasattr(s, "params") and k in s.params:
                            s.params[k] = v

            if isinstance(wrapper.instance, list):
                engine.strategies.extend(wrapper.instance)
            else:
                engine.strategies.append(wrapper.instance)

    log.info(f"Engine initialized with {len(engine.strategies)} strategies.")

    for s in engine.strategies:
        sid = getattr(s, "strategy_id", getattr(s, "name", "unknown"))
        if sid not in engine.strategy_stats:
            engine.strategy_stats[sid] = {
                "pnl": 0.0,
                "total_trades": 0,
                "buy_wins": 0,
                "buy_losses": 0,
                "sell_wins": 0,
                "sell_losses": 0,
                "tp_wins": 0,
                "be_wins": 0
            }

    # Track pointers into history for each timeframe/symbol to avoid re-scanning
    pointers = {sym: {t: 0 for t in relevant_tfs} for sym in assets + [BTC_SYMBOL]}
    # Advance pointers to where we pre-populated
    for sym in assets + [BTC_SYMBOL]:
        for t in relevant_tfs:
            while pointers[sym][t] < len(asset_history[sym][t]) and asset_history[sym][t][pointers[sym][t]]['ts'] + TF_SECONDS[t] <= START_DATE.timestamp():
                pointers[sym][t] += 1

    progress = Progress(len(timeline), label="BT Portfolio")
    chain.reset()

    # Remove artificial latency for backtests
    sim.latency_simulation = False

    overrides_dict = overrides or {}
    hb_interval = overrides_dict.get("heartbeat_interval", 30)
    last_hb_time = 0

    try:
        # Master timeline loop
        for step_idx, current_ts in enumerate(timeline):
            import tools.logger
            tools.logger.VIRTUAL_TIME = current_ts

            # Periodic Heartbeat in Backtest Console Output based on real elapsed time
            now_real = time.time()
            if now_real - last_hb_time >= hb_interval:
                from tools.publisher import ConsolePublisher
                wr = (engine.winning_trades / engine.total_trades * 100) if engine.total_trades > 0 else 0
                pr_val = engine.profit_ratio
                ConsolePublisher.publish_heartbeat(current_ts, engine.equity, engine.total_trades, wr, pr_val, len(engine.open_positions), engine.session_signals)
                last_hb_time = now_real

            # Step A: Update prices and simulate price action for all active assets
            for asset in assets:
                if asset not in candle_by_ts or current_ts not in candle_by_ts[asset]:
                    continue
                c = candle_by_ts[asset][current_ts]

                o, h, l, cl = c['o'], c['h'], c['l'], c['c']

                # Skip sub-candle simulation if idle to boost speed
                intra_candle_prices = [o, h, l, cl]
                if not sim.positions and not sim.pending_orders:
                    intra_candle_prices = [cl] # Only simulate close if idle

                # Update simulator's OHLCV
                sim.ohlcv[asset][tf].append(c)
                if len(sim.ohlcv[asset][tf]) > 1000: sim.ohlcv[asset][tf].pop(0)

                if tf in sim.confluence_history[asset]:
                    sim.confluence_history[asset][tf].append(cl)
                    if len(sim.confluence_history[asset][tf]) > 1000: sim.confluence_history[asset][tf].pop(0)

                # Simulate Price Action for this asset
                for price in intra_candle_prices:
                    sim.last_price[asset] = price
                    if asset in sim.books:
                        sim.books[asset].mid_price = price
                        sim.books[asset]._regenerate()

                        # Sync Engine's shadow books for tradability checks
                        if asset in engine.books:
                            engine.books[asset].bids = list(sim.books[asset].bids)
                            engine.books[asset].asks = list(sim.books[asset].asks)
                            engine.books[asset].timestamp = current_ts

            # Step B: Process orders ONCE for the shared simulator at this timestamp
            if sim.positions or sim.pending_orders:
                await sim._process_orders()

            # Step C: Synchronize BTC and other timeframes to the current timestamp
            for sym in assets + [BTC_SYMBOL]:
                for t in relevant_tfs:
                    if sym in assets and t == tf: continue

                    # Only sync history when needed (fully closed/completed bars only)
                    while pointers[sym][t] < len(asset_history[sym][t]):
                        new_c = asset_history[sym][t][pointers[sym][t]]
                        # Ensure the bar of timeframe t has fully closed before current_ts
                        if new_c['ts'] + TF_SECONDS[t] <= current_ts:
                            sim.ohlcv[sym][t].append(new_c)
                            if len(sim.ohlcv[sym][t]) > 1000: sim.ohlcv[sym][t].pop(0)

                            if t in sim.confluence_history[sym]:
                                sim.confluence_history[sym][t].append(new_c['c'])
                                if len(sim.confluence_history[sym][t]) > 1000: sim.confluence_history[sym][t].pop(0)

                            pointers[sym][t] += 1
                        else:
                            break

            # Step D: Check signals and place trades for all assets concurrently under the shared Engine
            # Respect MAX_CONCURRENT_POSITIONS globally!
            if (len(engine.open_positions) + len(engine.pending_entries)) < config.MAX_CONCURRENT_POSITIONS:
                for asset in assets:
                    # Sourced only if we have a candle at this timestamp
                    if asset not in candle_by_ts or current_ts not in candle_by_ts[asset]: continue
                    if (len(engine.open_positions) + len(engine.pending_entries)) >= config.MAX_CONCURRENT_POSITIONS:
                        break

                    book = sim.books[asset]
                    if book.best_bid <= 0: continue

                    # Predict signals for this asset
                    active_signals = []
                    if engine.strategies:
                        market_data = {
                            "symbol": asset,
                            "book": book,
                            "equity": engine.equity, # dynamically use actual shared equity
                            "features": None
                        }
                        for strat in engine.strategies:
                            if hasattr(strat, "is_ready") and not strat.is_ready(asset):
                                continue
                            if hasattr(strat, "get_entry_signal"):
                                if hasattr(strat, "model") and hasattr(strat.model, "simulator"):
                                    strat.model.simulator = sim
                                sig = strat.get_entry_signal(market_data)
                                if sig:
                                    engine.session_signals += 1
                                    sig["strategy_id"] = sig.get("strategy_id") or getattr(strat, "strategy_id", getattr(strat, "name", "unknown"))
                                    active_signals.append(sig)

                    for signal in active_signals:
                        # 1. Scoring Confluence Gating Check
                        feat = sim.get_features(asset)
                        if not feat:
                            continue

                        from ta.scoring import ScoringEngine
                        se = ScoringEngine()
                        strategy_id = signal.get("strategy_id", "unknown")

                        if strategy_id == "model":
                            scoring_result = se.evaluate(feat, side=signal["side"], config_context=config, dynamic_weights=engine.model.weights)
                        else:
                            scoring_result = se.evaluate(feat, side=signal["side"], config_context=config)

                        # Always write to the complete signals log file
                        engine._write_signals_log(asset, signal["side"], strategy_id, scoring_result)

                        if scoring_result["decision"] == "REJECTED":
                            continue

                        if not engine._asset_is_tradable(asset, signal["side"], features=feat, signal=signal):
                            continue

                        # Place trade via unified engine
                        kwargs = signal.copy()
                        for key in ["symbol", "side", "qty", "entry_price", "stop_price", "exit_price", "tp_price", "strategy_id"]:
                            kwargs.pop(key, None)

                        res = sim.place_trade_oco(
                            asset, signal["side"], signal.get("qty", 0),
                            signal["entry_price"], signal["stop_price"], signal.get("exit_price") or signal.get("tp_price"),
                            features=feat,
                            strategy_id=signal.get("strategy_id"),
                            **kwargs
                        )

                        if res and res.get("code") == "00000":
                            engine._write_metrics_log(asset, signal["side"], strategy_id, scoring_result)

            # Enforce protective safety limit checks (Drawdown, ROI, Max Trades, Duration)
            if sim.equity > peak_equity:
                peak_equity = sim.equity

            # 1. Drawdown Limit
            if peak_equity > 0 and sim.equity <= config.DRAWDOWN_LIMIT * peak_equity:
                log.critical(f"DRAWDOWN LIMIT HIT: equity={sim.equity:.2f}, peak={peak_equity:.2f} | Stopping Backtest.")
                break

            # 2. ROI Limit
            roi = (sim.equity / config.INITIAL_EQUITY - 1)
            if roi >= config.TOTAL_ROI_LIMIT:
                log.critical(f"ROI TARGET REACHED: equity={sim.equity:.2f}, ROI={roi*100:.1f}% | Stopping Backtest.")
                break

            # 3. Trade Count Limit
            if engine.total_trades >= config.MAX_TRADES_LIMIT:
                log.critical(f"TRADE LIMIT REACHED: {engine.total_trades} trades | Stopping Backtest.")
                break

            # 4. Duration Limit
            elapsed_real = time.time() - engine.start_time
            if elapsed_real >= config.MAX_DURATION:
                log.critical(f"DURATION LIMIT REACHED: {elapsed_real:.0f}s (Real) | Stopping Backtest.")
                break

            progress.update(1)
    except KeyboardInterrupt:
        log.warning("\n[CTRL+C] Portfolio backtest interrupted by user. Finalizing partial results...")
        if engine.open_positions:
            print("\n" + "="*60)
            print("CURRENT OPEN POSITIONS AT INTERRUPTION:")
            print("-" * 60)
            for pos_key, p in engine.open_positions.items():
                print(f"  - {pos_key:15} | Side: {p['side'].upper():4} | Qty: {p['qty']:8.3f} | Entry: {p['entry']:10.8f} | Margin: {p['margin']:.2f}")
            print("="*60 + "\n")

    # Format the individual asset performance output structures
    results = []
    for asset in assets:
        if asset not in asset_candles:
            continue
        ss = engine.asset_stats.get(asset, {"buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0, "pnl": 0.0, "buy_pnl": 0.0, "sell_pnl": 0.0})
        side_stats = {
            "long": {"trades": ss["buy_wins"] + ss["buy_losses"], "wins": ss["buy_wins"], "pnl": ss["buy_pnl"]},
            "short": {"trades": ss["sell_wins"] + ss["sell_losses"], "wins": ss["sell_wins"], "pnl": ss["sell_pnl"]}
        }
        total_trades = ss["buy_wins"] + ss["buy_losses"] + ss["sell_wins"] + ss["sell_losses"]
        win_rate = ((ss["buy_wins"] + ss["sell_wins"]) / total_trades * 100) if total_trades > 0 else 0
        total_margin = ss.get("total_margin", 0)
        avg_roe = (ss["pnl"] / total_margin * 100) if total_margin > 0 else 0

        results.append({
            "asset": asset,
            "tf": tf,
            "roe": avg_roe,
            "pnl": ss["pnl"],
            "roi": (ss["pnl"] / config.INITIAL_EQUITY * 100),
            "win_rate": win_rate,
            "trades": total_trades,
            "equity": engine.equity, # final portfolio equity
            "side_stats": side_stats,
            "strategy_stats": engine.strategy_stats,
            "no_data": False
        })

    import tools.logger
    tools.logger.VIRTUAL_TIME = None

    return results

def print_results(results):
    date_range = f"{START_DATE.strftime('%Y-%m-%d')} to {END_DATE.strftime('%Y-%m-%d')}"
    print("\n" + "="*165)
    print(f"BACKTEST RESULTS")
    print("-" * 165)
    print(f"{'Date Range':<22} | {'Asset':<10} | {'TF':<5} | {'Win% (L/S)':>12} | {'PnL (L/S)':>15} | {'ROE%':>8} | {'PnL':>10} | {'ROI%':>7} | {'Trades':>8} | {'Equity':>12}")
    print("-" * 165)

    total_pnl = 0
    total_account_roi = 0
    total_trades = 0
    total_l_wins = 0
    total_l_trades = 0
    total_l_pnl = 0
    total_s_wins = 0
    total_s_trades = 0
    total_s_pnl = 0

    for r in results:
        if not r: continue

        if r.get("no_data"):
             print(f"{date_range:<22} | {r['asset']:<10} | {'N/A':<5} | {'NO DATA':>12} | {'N/A':>15} | {'N/A':>8} | {'N/A':>10} | {'N/A':>7} | {'0':>8} | {'N/A':>12}")
             continue

        ss = r['side_stats']
        win_l = (ss['long']['wins'] / ss['long']['trades'] * 100) if ss['long']['trades'] > 0 else 0
        win_s = (ss['short']['wins'] / ss['short']['trades'] * 100) if ss['short']['trades'] > 0 else 0
        win_ls = f"{win_l:.0f}%/{win_s:.0f}%"
        pnl_ls = f"{ss['long']['pnl']:.1f}/{ss['short']['pnl']:.1f}"

        print(f"{date_range:<22} | {r['asset']:<10} | {r['tf']:<5} | {win_ls:>12} | {pnl_ls:>15} | {r['roe']:>8.1f}% | {r['pnl']:>10.2f} | {r['roi']:>7.1f}% | {r['trades']:>8} | {r['equity']:>12.2f}")

        total_pnl += r['pnl']
        total_account_roi += r['roi']
        total_trades += r['trades']
        total_l_wins += ss['long']['wins']
        total_l_trades += ss['long']['trades']
        total_l_pnl += ss['long']['pnl']
        total_s_wins += ss['short']['wins']
        total_s_trades += ss['short']['trades']
        total_s_pnl += ss['short']['pnl']

    if results:
        print("-" * 165)
        ov_win_l = (total_l_wins / total_l_trades * 100) if total_l_trades > 0 else 0
        ov_win_s = (total_s_wins / total_s_trades * 100) if total_s_trades > 0 else 0
        ov_win_ls = f"{ov_win_l:.0f}%/{ov_win_s:.0f}%"
        ov_pnl_ls = f"{total_l_pnl:.1f}/{total_s_pnl:.1f}"

        # Average ROI across all tested assets
        ov_roi = total_account_roi / len(results)

        print(f"{'OVERALL':<22} | {'ALL':<10} | {'MIX':<5} | {ov_win_ls:>12} | {ov_pnl_ls:>15} | {'N/A':>8} | {total_pnl:>10.2f} | {ov_roi:>7.1f}% | {total_trades:>8} | {'N/A':>12}")

    # [TECH-001] Strategy Breakdown Summary Table (Deduplicated by Strategy ID/Stats Object)
    strat_aggregates = {}
    seen_stats_objects = set()
    for r in results:
        if not r or r.get("no_data"): continue
        stats_obj = r.get("strategy_stats")
        if not stats_obj: continue

        # In portfolio mode, multiple asset result dicts reference the identical shared strategy_stats object.
        # To avoid duplicating PnL and trade counts, we only process each unique strategy_stats object once.
        if id(stats_obj) in seen_stats_objects:
            continue
        seen_stats_objects.add(id(stats_obj))

        for sid, stats in stats_obj.items():
            if sid not in strat_aggregates:
                strat_aggregates[sid] = {"pnl": 0, "trades": 0, "wins": 0}
            strat_aggregates[sid]["pnl"] += stats["pnl"]
            strat_aggregates[sid]["trades"] += stats["total_trades"]
            strat_aggregates[sid]["wins"] += (stats["buy_wins"] + stats["sell_wins"])

    if strat_aggregates:
        print("\nSTRATEGY BREAKDOWN")
        print("-" * 60)
        print(f"{'Strategy':<25} | {'PnL':>10} | {'Win%':>8} | {'Trades':>8}")
        print("-" * 60)
        for sid, agg in strat_aggregates.items():
            wr = (agg["wins"] / agg["trades"] * 100) if agg["trades"] > 0 else 0
            print(f"{sid:<25} | {agg['pnl']:>10.2f} | {wr:>7.1f}% | {agg['trades']:>8}")
        print("-" * 60)

    print("="*165 + "\n")

def get_required_timeframes(chain: ConfluenceChain) -> List[str]:
    """
    [TECH-001] Unified timeframe discovery logic.
    [REPAIR-20260702] Strict scoping: Only include what's explicitly required
    by the strategies in the chain. No 'forced' 1m unless explicitly needed.
    """
    tfs = set()
    for segment in chain.segments:
        for wrapper in segment:
            # Handle list of strategies (Family)
            strategies = wrapper.instance if isinstance(wrapper.instance, list) else [wrapper.instance]
            for strat in strategies:
                # 1. Check explicit required_history (Class-based strategies)
                if hasattr(strat, "required_history"):
                    tfs.update(strat.required_history.keys())

                # 2. Check range_tf in params
                if hasattr(strat, "params") and "range_tf" in strat.params:
                    tfs.add(strat.params["range_tf"])

            # 3. Check CLI overrides
            for p in wrapper.params:
                if "range_tf=" in p:
                    tfs.add(p.split("=")[1])
            if "range_tf" in wrapper.overrides:
                tfs.add(wrapper.overrides["range_tf"])
            if "timeframe" in wrapper.overrides:
                tfs.add(wrapper.overrides["timeframe"])

    # Fallback: if no timeframes discovered, default to 1m for simulation
    if not tfs:
        tfs.add("1m")

    return list(tfs)

async def main():
    global START_DATE, END_DATE

    # Ensure they are set to defaults at start of main
    START_DATE = DEFAULT_START_DATE
    END_DATE = DEFAULT_END_DATE

    if len(sys.argv) < 2:
        print("Usage: python backtest.py [strategy_query] [optional: START_DATE (YYYY-MM-DD)] [optional: END_DATE (YYYY-MM-DD)]")
        print("Examples:")
        print('  python backtest.py "engulfing + sentiment 10 20 -> fvg 3 25 1"')
        print('  python backtest.py "engulfing" "(sentiment 10 90)"')
        print('  python backtest.py "sentiment 10 30" 2026-05-01 2026-06-01')
        return

    query_parts = []
    import re
    date_regex = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    dates_found = []
    overrides = {}
    assets_to_run = DEFAULT_ASSETS

    for arg in sys.argv[1:]:
        # Detect dates (YYYY-MM-DD)
        if date_regex.match(arg):
            dates_found.append(arg)
        elif "=" in arg:
            k, v = arg.split("=", 1)
            if k == "assets":
                assets_to_run = v.split(",")
            else:
                try:
                    import ast
                    overrides[k] = ast.literal_eval(v)
                except:
                    overrides[k] = v
        else:
            query_parts.append(arg)

    if len(dates_found) >= 1:
        START_DATE = datetime.strptime(dates_found[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if len(dates_found) >= 2:
        END_DATE = datetime.strptime(dates_found[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)

    if not query_parts:
        print("Error: No strategy segments provided.")
        return

    # Join with -> if segments were passed as separate arguments
    # This allows: python backtest.py "A + B" "C" -> A + B -> C
    if query_parts[0] == "strategies":
        query_cmd = "strategies"
    else:
        query_cmd = " -> ".join(query_parts)

    db = Database()
    client = None

    try:
        # [REPAIR-20260708] Proactive Rate Limiting (98% safety cap)
        from engine.exchanges.bitget import BitgetExchange
        limiter = RateLimiter(rps=BitgetExchange.DEFAULT_RPS, safety_factor=0.98)
        client = BitGetClient(config.BITGET_API_KEY, config.BITGET_SECRET_KEY, config.BITGET_PASSPHRASE, rate_limiter=limiter)

        # Asset Discovery if DEFAULT_ASSETS is empty and no assets CLI argument
        if not assets_to_run:
            assets_to_run = await discover_assets(client)

        try:
            # Apply global overrides to config module if specified
            for k, v in overrides.items():
                if hasattr(config, k):
                    setattr(config, k, v)
                    log.info(f"Overriding config.{k} = {v}")

            chain = parse_confluence_command(query_cmd)
            # Apply overrides to wrappers in the chain
            for segment in chain.segments:
                for wrapper in segment:
                    wrapper.overrides = overrides
                    # Re-load instance with overrides
                    wrapper.instance = wrapper._load_strategy(wrapper.path)
        except Exception as e:
            print(f"Error parsing command: {e}")
            return

        # 1. Acquisition of data (Using unified discovery)
        required_tfs = get_required_timeframes(chain)
        try:
            await download_historical_data(client, db, assets_to_run, required_tfs, chain=chain)
        except KeyboardInterrupt:
            log.warning("\n[CTRL+C] Data acquisition interrupted by user. Exiting.")
            return

        # 2. Run backtests based on toggle
        all_results = []

        if USE_PORTFOLIO_MODE:
            log.info("Running in Concurrent Portfolio Mode (Sharing Capital)...")
            all_results = await run_backtest_portfolio(chain, db, client, assets_to_run, "1m", overrides=overrides)
        else:
            log.info("Running in Isolated Single-Asset Mode...")
            for asset in assets_to_run:
                # Only run for the entry timeframe (1m) as requested by user
                res = await run_backtest(chain, db, client, asset, "1m", overrides=overrides)
                if res is None:
                     res = {
                         "asset": asset,
                         "no_data": True,
                         "roi": 0,
                         "pnl": 0,
                         "trades": 0,
                         "side_stats": {
                             "long": {"wins": 0, "trades": 0, "pnl": 0},
                             "short": {"wins": 0, "trades": 0, "pnl": 0}
                         }
                     }
                all_results.append(res)

        # Ensure all requested assets are present in the final table (even if they had no data)
        final_results = []
        run_assets = [r["asset"] for r in all_results]
        for asset in assets_to_run:
            if asset in run_assets:
                for r in all_results:
                    if r["asset"] == asset:
                        final_results.append(r)
                        break
            else:
                 final_results.append({
                     "asset": asset,
                     "no_data": True,
                     "roi": 0,
                     "pnl": 0,
                     "trades": 0,
                     "side_stats": {
                         "long": {"wins": 0, "trades": 0, "pnl": 0},
                         "short": {"wins": 0, "trades": 0, "pnl": 0}
                     }
                 })

        # Print Milestone Reports
        for asset in assets_to_run:
            found_report = False
            for segment in chain.segments:
                for wrapper in segment:
                    if hasattr(wrapper.instance, "get_milestone_report"):
                        report = wrapper.instance.get_milestone_report()
                        if report:
                            if not found_report:
                                print(f"\n[Milestone Report: {asset}]")
                                found_report = True
                            print(report)

        # 3. Output Table
        print_results(final_results)

    finally:
        if client:
            try:
                await client.close()
            except Exception as ce:
                log.error(f"Error closing client: {ce}")
        try:
            db.stop()
        except Exception as de:
            log.error(f"Error stopping database: {de}")

        # Restore original streams and close file
        try:
            sys.stdout = stdout_tee.original_stream
            sys.stderr = stderr_tee.original_stream
            stdout_tee.close()
            stderr_tee.close()
        except Exception as te:
            pass

if __name__ == "__main__":
    asyncio.run(main())
