import sys
import os
import asyncio
import math
import logging
import time
import importlib
import importlib.util
import inspect
from datetime import datetime
import pytz
from typing import List, Dict, Any, Optional

# Ensure project root is in path
sys.path.append(os.getcwd())

import config
from database import Database
from bitget_client import BitGetClient
from engine.simulation import SimulationEngine
from config import BTC_SYMBOL, AVAILABLE_TIMEFRAMES
from tools.trading_utils import calculate_fees, calculate_pnl, calculate_net_pnl, calculate_position_size

# --- Backtest Settings ---
PROXIMITY_LIMIT = 5
RESET_PROXIMITY_ON_REPEAT = True
DIRECTION_MODE = "strict" # "strict" or "open"

DEFAULT_ASSETS = ["ETHUSDT", "HBARUSDT", "UNIUSDT", "GRTUSDT"]
DEFAULT_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1H"]
# June 1, 2022 to June 1, 2026 (Global Range)
MAX_START_DATE = datetime(2022, 6, 1, tzinfo=pytz.UTC)
MAX_END_DATE = datetime(2026, 6, 1, tzinfo=pytz.UTC)

# Default to 1 month for speed (May 2026)
DEFAULT_START_DATE = datetime(2026, 5, 1, tzinfo=pytz.UTC)
DEFAULT_END_DATE = datetime(2026, 6, 1, tzinfo=pytz.UTC)

START_DATE = DEFAULT_START_DATE
END_DATE = DEFAULT_END_DATE

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backtest")

class Progress:
    def __init__(self, total, label="Progress"):
        self.total = total
        self.current = 0
        self.label = label
        self.start_time = time.time()

    def update(self, amount=1):
        self.current += amount
        pct = (self.current / self.total) * 100
        elapsed = time.time() - self.start_time
        rate = self.current / elapsed if elapsed > 0 else 0
        eta = (self.total - self.current) / rate if rate > 0 else 0

        sys.stdout.write(f"\r{self.label}: [{self.current}/{self.total}] {pct:.1f}% | ETA: {int(eta)}s  ")
        sys.stdout.flush()
        if self.current >= self.total:
            print()

async def download_historical_data(client: BitGetClient, db: Database, assets: List[str], timeframes: List[str]):
    log.info("Acquiring historical data...")

    target_start_ms = int(START_DATE.timestamp() * 1000)
    target_end_ms = int(END_DATE.timestamp() * 1000)

    for asset in assets:
        for tf in timeframes:
            # Check what we already have in the required range
            min_ts, max_ts, count = db.get_candle_range_stats(asset, tf, START_DATE.timestamp(), END_DATE.timestamp())

            # Calculate expected count (approximate)
            tf_seconds = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400, "1D": 86400}
            expected = (END_DATE.timestamp() - START_DATE.timestamp()) / tf_seconds[tf]

            if count >= expected * 0.9: # 90% coverage is good enough to skip
                log.info(f"Data for {asset} {tf} already exists in DB ({count} candles).")
                continue

            current_end = target_end_ms
            log.info(f"Downloading {asset} {tf} from {START_DATE} to {END_DATE}...")

            progress = Progress(int(expected), label=f"Downloading {asset} {tf}")

            while current_end > target_start_ms:
                # [OPT-001] Check for existing data block to avoid redundant API calls
                if db.check_candle_exists(asset, tf, current_end / 1000):
                    # We have this candle. Now find the earliest candle in this continuous block.
                    # We'll use a simpler heuristic: skip back 200 candles and check again.
                    jump_ms = tf_seconds[tf] * 200 * 1000
                    if db.check_candle_exists(asset, tf, (current_end - jump_ms) / 1000):
                        current_end -= jump_ms
                        progress.update(200)
                        continue

                candles = await client.request("GET", "/api/v2/mix/market/history-candles", params={
                    "symbol": asset,
                    "productType": "usdt-futures",
                    "granularity": tf,
                    "endTime": str(current_end),
                    "limit": "200"
                })

                data = candles.get("data", [])
                if not data:
                    log.warning(f"No more data returned for {asset} {tf} at {current_end}")
                    break

                valid_count = 0
                for c in data:
                    ts_ms = int(c[0])
                    o, h, l, cl, v = map(float, c[1:6])
                    if ts_ms < target_start_ms:
                        current_end = 0
                        # Don't break yet, process remaining in this batch if they are >= target
                        if ts_ms >= target_start_ms:
                             db.save_candle(asset, tf, ts_ms / 1000, o, h, l, cl, v)
                             valid_count += 1
                        continue

                    db.save_candle(asset, tf, ts_ms / 1000, o, h, l, cl, v)
                    valid_count += 1
                    current_end = min(current_end, ts_ms - 1)

                if valid_count == 0:
                    break

                progress.update(len(data))
                # Small sleep to respect rate limits
                await asyncio.sleep(0.1)

def find_strategy_file(query: str) -> Optional[str]:
    # Check strategies/ first
    for f in os.listdir("strategies"):
        if query in f and f.endswith(".py"):
            return os.path.join("strategies", f)

    # Recursively search ta/
    matches = []

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
        module_name = path.replace("/", ".").replace("\\", ".")
        if module_name.endswith(".py"):
            module_name = module_name[:-3]

        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Check if it's a new class-based strategy
        if "strategies/" in path:
            for name, obj in module.__dict__.items():
                if isinstance(obj, type) and name != "JBaseStrategy" and "Strategy" in name:
                    return obj(simulator=self.simulator, config_overrides=self.overrides)

        return module

    def get_signal(self, ohlcv, tf, symbol=None):
        if hasattr(self.instance, "get_entry_signal"):
            # New Strategy class
            # We need to wrap it to match the expected return of backtest.py
            # Backtest expects ohlcv and tf, Strategy expects market_data
            # We mock the market_data for the strategy
            market_data = {
                "symbol": symbol or "BACKTEST",
                "book": type('obj', (object,), {'best_bid': ohlcv[-1]['c'], 'best_ask': ohlcv[-1]['c']}),
                "equity": config.INITIAL_EQUITY,
                "features": None # Simulator will be used if None
            }
            return self.instance.get_entry_signal(market_data)

        return self.instance.get_signal(ohlcv, tf, params=self.params)

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

async def run_backtest(chain, db: Database, client: BitGetClient, asset: str, tf: str):
    # BT-002: Reset config to default before each asset/tf run to ensure no leakage from strategies
    import importlib, config
    importlib.reload(config)

    # USE THE UNIFIED SIMULATION ENGINE
    from engine.core import Engine
    engine = Engine(use_db=False)
    sim = engine.exchange
    sim.db = db

    # Warm up with specs
    specs = await client.get_symbols()
    spec_map = {s['symbol']: s for s in specs}
    sim.contract_specs = spec_map
    sim.leverage_limits = {s: float(spec_map[s].get('maxLever', 20)) for s in spec_map if s in [asset, BTC_SYMBOL]}
    sim.discovered_assets = [asset]

    from orderbook import SimulatedOrderBook
    for sym in [asset, BTC_SYMBOL]:
        sim.books[sym] = SimulatedOrderBook(sym, 1.0)

    # Load candles from DB within the specified range
    candles = db.get_candles_in_range(asset, tf, START_DATE.timestamp(), END_DATE.timestamp())
    if not candles:
        return None

    if len(candles) < 10:
        return None

    # Inject ALL timeframes for this asset and BTC for confluence
    history_sec = 86400 * 3 # 3 days history for indicators (balance speed/accuracy)
    asset_history = {}
    for sym in [asset, BTC_SYMBOL]:
        sim.ohlcv[sym] = {t: [] for t in AVAILABLE_TIMEFRAMES}
        sim.confluence_history[sym] = {t: [] for t in ["15m", "1H", "4H", "1D", "1W"]}
        asset_history[sym] = {}
        for t in AVAILABLE_TIMEFRAMES:
            c_data = db.get_candles_in_range(sym, t, START_DATE.timestamp() - history_sec, END_DATE.timestamp())
            data = [{"ts": ts, "o": o, "h": h, "l": l, "c": cl, "v": v} for ts, o, h, l, cl, v in c_data]
            asset_history[sym][t] = data

            # Pre-populate simulator with history UP TO START_DATE
            for c in data:
                if c['ts'] < START_DATE.timestamp():
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

    progress = Progress(len(full_history) - start_idx, label=f"Backtesting {asset} {tf}")
    chain.reset()

    # Initialize wrappers with sim
    for segment in chain.segments:
        for wrapper in segment:
            wrapper.simulator = sim
            wrapper.instance = wrapper._load_strategy(wrapper.path)

    # Simulation Loop using unified engine
    for i in range(start_idx, len(full_history)):
        c = full_history[i]
        o, h, l, cl = c['o'], c['h'], c['l'], c['c']

        # Update simulator's OHLCV for current candle
        sim.ohlcv[asset][tf].append(c)
        if tf in sim.confluence_history[asset]:
            sim.confluence_history[asset][tf].append(cl)

        # [BT-001] Simulate Intra-Candle Price Action (O -> H/L -> C)
        for price in [o, h, l, cl]:
            sim.last_price[asset] = price
            if asset in sim.books:
                sim.books[asset].mid_price = price
                sim.books[asset]._regenerate()
            await sim._process_orders()

        # 2. Check for entry signal
        if len(sim.ohlcv[asset][tf]) >= 2:
            # Synchronize BTC and other timeframes to the current timestamp
            current_ts = c['ts']
            for sym in [asset, BTC_SYMBOL]:
                for t in AVAILABLE_TIMEFRAMES:
                    if sym == asset and t == tf: continue
                    # Add candles from history up to current_ts
                    while len(sim.ohlcv[sym][t]) < len(asset_history[sym][t]) and asset_history[sym][t][len(sim.ohlcv[sym][t])]['ts'] <= current_ts:
                        new_c = asset_history[sym][t][len(sim.ohlcv[sym][t])]
                        sim.ohlcv[sym][t].append(new_c)
                        if t in sim.confluence_history[sym]:
                            sim.confluence_history[sym][t].append(new_c['c'])

            signal = chain.check(sim.ohlcv[asset][tf][-200:], tf, symbol=asset)
            if signal:
                # Place trade via unified engine
                res = sim.place_trade_oco(
                    asset, signal["side"], signal.get("qty", 0),
                    signal["entry_price"], signal["stop_price"], signal["exit_price"],
                    features=signal # Pass features so they are available for reporting
                )

        progress.update(1)

    roi = (sim.equity / config.INITIAL_EQUITY - 1) * 100

    # Capture results from Engine
    ss = engine.asset_stats.get(asset, {"buy_wins": 0, "buy_losses": 0, "sell_wins": 0, "sell_losses": 0, "pnl": 0.0, "buy_pnl": 0.0, "sell_pnl": 0.0})
    side_stats = {
        "long": {"trades": ss["buy_wins"] + ss["buy_losses"], "wins": ss["buy_wins"], "pnl": ss["buy_pnl"]},
        "short": {"trades": ss["sell_wins"] + ss["sell_losses"], "wins": ss["sell_wins"], "pnl": ss["sell_pnl"]}
    }

    avg_roe = (sum(engine.pos_pnl.values()) / engine.total_trades) if engine.total_trades > 0 else 0 # Rough estimate

    return {
        "asset": asset,
        "tf": tf,
        "roe": avg_roe,
        "pnl": ss["pnl"],
        "roi": roi,
        "win_rate": (engine.winning_trades / engine.total_trades * 100) if engine.total_trades > 0 else 0,
        "trades": engine.total_trades,
        "equity": sim.equity,
        "side_stats": side_stats
    }

def print_results(results):
    date_range = f"{START_DATE.strftime('%Y-%m-%d')} to {END_DATE.strftime('%Y-%m-%d')}"
    print("\n" + "="*165)
    print(f"BACKTEST RESULTS")
    print("-" * 165)
    print(f"{'Date Range':<22} | {'Asset':<10} | {'TF':<5} | {'Win% (L/S)':>12} | {'PnL (L/S)':>15} | {'ROE%':>8} | {'PnL':>10} | {'ROI%':>7} | {'Trades':>8} | {'Equity':>12}")
    print("-" * 165)

    total_pnl = 0
    total_trades = 0
    total_l_wins = 0
    total_l_trades = 0
    total_l_pnl = 0
    total_s_wins = 0
    total_s_trades = 0
    total_s_pnl = 0

    for r in results:
        if not r: continue
        ss = r['side_stats']
        win_l = (ss['long']['wins'] / ss['long']['trades'] * 100) if ss['long']['trades'] > 0 else 0
        win_s = (ss['short']['wins'] / ss['short']['trades'] * 100) if ss['short']['trades'] > 0 else 0
        win_ls = f"{win_l:.0f}%/{win_s:.0f}%"
        pnl_ls = f"{ss['long']['pnl']:.1f}/{ss['short']['pnl']:.1f}"

        print(f"{date_range:<22} | {r['asset']:<10} | {r['tf']:<5} | {win_ls:>12} | {pnl_ls:>15} | {r['roe']:>8.1f}% | {r['pnl']:>10.2f} | {r['roi']:>7.1f}% | {r['trades']:>8} | {r['equity']:>12.2f}")

        total_pnl += r['pnl']
        total_trades += r['trades']
        total_l_wins += ss['long']['wins']
        total_l_trades += ss['long']['trades']
        total_l_pnl += ss['long']['pnl']
        total_s_wins += ss['short']['wins']
        total_s_trades += ss['short']['trades']
        total_s_pnl += ss['short']['pnl']

    if total_trades > 0:
        print("-" * 165)
        ov_win_l = (total_l_wins / total_l_trades * 100) if total_l_trades > 0 else 0
        ov_win_s = (total_s_wins / total_s_trades * 100) if total_s_trades > 0 else 0
        ov_win_ls = f"{ov_win_l:.0f}%/{ov_win_s:.0f}%"
        ov_pnl_ls = f"{total_l_pnl:.1f}/{total_s_pnl:.1f}"
        ov_roi = (total_pnl / (config.INITIAL_EQUITY * len([x for x in results if x]))) * 100

        print(f"{'OVERALL':<22} | {'ALL':<10} | {'MIX':<5} | {ov_win_ls:>12} | {ov_pnl_ls:>15} | {'N/A':>8} | {total_pnl:>10.2f} | {ov_roi:>7.1f}% | {total_trades:>8} | {'N/A':>12}")

    print("="*165 + "\n")

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

    for arg in sys.argv[1:]:
        # Detect dates (YYYY-MM-DD)
        if date_regex.match(arg):
            dates_found.append(arg)
        elif "=" in arg:
            k, v = arg.split("=", 1)
            try:
                import ast
                overrides[k] = ast.literal_eval(v)
            except:
                overrides[k] = v
        else:
            query_parts.append(arg)

    if len(dates_found) >= 1:
        START_DATE = datetime.strptime(dates_found[0], "%Y-%m-%d").replace(tzinfo=pytz.UTC)
    if len(dates_found) >= 2:
        END_DATE = datetime.strptime(dates_found[1], "%Y-%m-%d").replace(tzinfo=pytz.UTC)

    if not query_parts:
        print("Error: No strategy segments provided.")
        return

    # Join with -> if segments were passed as separate arguments
    # This allows: python backtest.py "A + B" "C" -> A + B -> C
    query_cmd = " -> ".join(query_parts)

    try:
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

    db = Database()
    client = BitGetClient(config.BITGET_API_KEY, config.BITGET_SECRET_KEY, config.BITGET_PASSPHRASE)

    # 1. Acquisition of data
    await download_historical_data(client, db, DEFAULT_ASSETS, DEFAULT_TIMEFRAMES)

    # 2. Run backtests
    all_results = []

    for asset in DEFAULT_ASSETS:
        for tf in DEFAULT_TIMEFRAMES:
            res = await run_backtest(chain, db, client, asset, tf)
            all_results.append(res)

    # 3. Output Table
    print_results(all_results)

    await client.close()
    db.stop()

if __name__ == "__main__":
    asyncio.run(main())
