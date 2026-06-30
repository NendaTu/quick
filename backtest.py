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
                import sqlite3
                with sqlite3.connect(db.db_path) as conn:
                    # Check if we have the candle at current_end
                    cursor = conn.execute("""
                        SELECT timestamp FROM candles
                        WHERE symbol = ? AND timeframe = ? AND timestamp = ?
                    """, (asset, tf, current_end / 1000))
                    if cursor.fetchone():
                        # We have this candle. Now find the earliest candle in this continuous block.
                        # We'll use a simpler heuristic: skip back 200 candles and check again.
                        # If we have that too, we skip.
                        jump_ms = tf_seconds[tf] * 200 * 1000
                        cursor = conn.execute("""
                            SELECT timestamp FROM candles
                            WHERE symbol = ? AND timeframe = ? AND timestamp = ?
                        """, (asset, tf, (current_end - jump_ms) / 1000))
                        if cursor.fetchone():
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
    def __init__(self, path: str, params: List[str] = None, ignore_direction: bool = False, is_flipped: bool = False):
        self.path = path
        self.params = params or []
        self.ignore_direction = ignore_direction
        self.is_flipped = is_flipped
        self.module = self._load_module(path)

    def _load_module(self, path):
        module_name = path.replace("/", ".").replace("\\", ".")
        if module_name.endswith(".py"):
            module_name = module_name[:-3]

        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def get_signal(self, ohlcv, tf):
        return self.module.get_signal(ohlcv, tf, params=self.params)

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

    def check(self, ohlcv, tf):
        if not self.segments:
            return None

        # 1. Evaluate current segment
        current_segment = self.segments[self.current_segment_idx]
        segment_results = [s.get_signal(ohlcv, tf) for s in current_segment]

        # All must signal in the same direction (if not ignored)
        direction = None
        all_match = True

        for i, res in enumerate(segment_results):
            if res is None:
                all_match = False
                break

            sig_dir = res["side"]
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
        # Split strictly by "+" for simultaneous
        parts = [p.strip() for p in step.split("+")]

        wrappers = []
        for p in parts:
            if not p: continue

            ignore_dir = False
            if p.endswith("~"):
                ignore_dir = True
                p = p[:-1].strip()

            is_flipped = False
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
    # Load contract specs for precision
    specs = await client.get_symbols()
    asset_spec = next((s for s in specs if s['symbol'] == asset), {})
    vol_place = int(asset_spec.get('volumePlace', 3))
    price_place = int(asset_spec.get('pricePlace', 2))

    # Load candles from DB within the specified range
    candles = db.get_candles_in_range(asset, tf, START_DATE.timestamp(), END_DATE.timestamp())
    if not candles:
        return None

    if len(candles) < 10:
        return None

    equity = config.INITIAL_EQUITY
    total_trades = 0
    wins = 0
    pnl = 0.0
    total_roe = 0.0

    # Side-based stats
    side_stats = {
        "buy": {"trades": 0, "wins": 0, "pnl": 0.0},
        "sell": {"trades": 0, "wins": 0, "pnl": 0.0}
    }

    open_pos = None

    # Simple simulation loop
    # We use a window of candles to pass to the strategy
    window_size = 200

    ohlcv_history = []

    progress = Progress(len(candles), label=f"Backtesting {asset} {tf}")
    chain.reset()

    for i in range(len(candles)):
        c = candles[i]
        ts, o, h, l, cl, v = c
        ohlcv_history.append({"ts": ts, "o": o, "h": h, "l": l, "c": cl, "v": v})

        if open_pos:
            # Check for exit (SL/TP)
            side = open_pos["side"]
            entry = open_pos["entry_price"]
            sl = open_pos["stop_price"]
            tp = open_pos["exit_price"]

            exit_price = None
            exit_type = None

            if side == "buy":
                if l <= sl:
                    exit_price = sl
                    exit_type = "sl"
                elif h >= tp:
                    exit_price = tp
                    exit_type = "tp"
            else:
                if h >= sl:
                    exit_price = sl
                    exit_type = "sl"
                elif l <= tp:
                    exit_price = tp
                    exit_type = "tp"

            if exit_price:
                # Determine if exit hit SL or TP
                is_tp = exit_type == "tp"
                # Use TAKER fee for SL, MAKER for TP if limit
                exit_maker = (is_tp and config.TP_ORDER_TYPE == "limit")

                net_pnl = calculate_net_pnl(open_pos["qty"], entry, exit_price, side, entry_maker=False, exit_maker=exit_maker)

                # Apply slippage (usually only for taker exits)
                if not exit_maker:
                    slippage_loss = exit_price * open_pos["qty"] * config.EXPECTED_SLIPPAGE
                    net_pnl -= slippage_loss

                # Calculate ROE for this trade (using 20x leverage as baseline for comparison)
                margin = (open_pos["qty"] * entry) / 20
                trade_roe = (net_pnl / margin) * 100 if margin > 0 else 0
                total_roe += trade_roe

                equity += net_pnl
                pnl += net_pnl
                total_trades += 1

                side_stats[side]["trades"] += 1
                side_stats[side]["pnl"] += net_pnl

                if net_pnl > 0:
                    wins += 1
                    side_stats[side]["wins"] += 1

                open_pos = None

        else:
            # Check for entry
            if len(ohlcv_history) >= 2:
                signal = chain.check(ohlcv_history[-window_size:], tf)
                if signal:
                    # Execute entry
                    # Using shared calculation for consistency with Engine/Simulator
                    entry_maker = (config.ENTRY_ORDER_TYPE == "limit")
                    sl_maker = (config.SL_ORDER_TYPE == "limit")

                    qty = calculate_position_size(
                        equity,
                        config.RISK_PER_TRADE,
                        signal["entry_price"],
                        signal["stop_price"],
                        entry_maker=entry_maker,
                        exit_maker=sl_maker,
                        fee_aware=config.FEE_AWARE_SIZING
                    )

                    if qty > 0:
                        # Apply precision
                        qty = math.floor(qty * (10 ** vol_place)) / (10 ** vol_place)

                        # Re-check qty after precision (might have become 0)
                        if qty <= 0:
                            progress.update(1)
                            continue

                        # Apply slippage on entry if taker
                        entry_price = signal["entry_price"]
                        if not entry_maker:
                            entry_price *= (1 + config.EXPECTED_SLIPPAGE if signal["side"] == "buy" else 1 - config.EXPECTED_SLIPPAGE)
                        entry_price = round(entry_price, price_place)

                        open_pos = {
                            "side": signal["side"],
                            "qty": qty,
                            "entry_price": entry_price,
                            "stop_price": signal["stop_price"],
                            "exit_price": signal["exit_price"]
                        }

        progress.update(1)

    roi = (equity / config.INITIAL_EQUITY - 1) * 100
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    avg_roe = (total_roe / total_trades) if total_trades > 0 else 0

    return {
        "asset": asset,
        "tf": tf,
        "roe": avg_roe,
        "pnl": pnl,
        "roi": roi,
        "win_rate": win_rate,
        "trades": total_trades,
        "equity": equity,
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
        win_l = (ss['buy']['wins'] / ss['buy']['trades'] * 100) if ss['buy']['trades'] > 0 else 0
        win_s = (ss['sell']['wins'] / ss['sell']['trades'] * 100) if ss['sell']['trades'] > 0 else 0
        win_ls = f"{win_l:.0f}%/{win_s:.0f}%"
        pnl_ls = f"{ss['buy']['pnl']:.1f}/{ss['sell']['pnl']:.1f}"

        print(f"{date_range:<22} | {r['asset']:<10} | {r['tf']:<5} | {win_ls:>12} | {pnl_ls:>15} | {r['roe']:>8.1f}% | {r['pnl']:>10.2f} | {r['roi']:>7.1f}% | {r['trades']:>8} | {r['equity']:>12.2f}")

        total_pnl += r['pnl']
        total_trades += r['trades']
        total_l_wins += ss['buy']['wins']
        total_l_trades += ss['buy']['trades']
        total_l_pnl += ss['buy']['pnl']
        total_s_wins += ss['sell']['wins']
        total_s_trades += ss['sell']['trades']
        total_s_pnl += ss['sell']['pnl']

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

    if len(sys.argv) < 2:
        print("Usage: python backtest.py [strategy_query] [optional: START_DATE (YYYY-MM-DD)] [optional: END_DATE (YYYY-MM-DD)]")
        print("Examples:")
        print('  python backtest.py "engulfing + sentiment 10 20 -> fvg 3 25 1"')
        print('  python backtest.py "engulfing" "(sentiment 10 90)"')
        print('  python backtest.py "sentiment 10 30" 2026-05-01 2026-06-01')
        return

    query_cmd = sys.argv[1]

    # Parse optional dates from the end of the argument list
    for arg in sys.argv[2:]:
        if "-" in arg and len(arg) == 10:
            try:
                dt = datetime.strptime(arg, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
                if START_DATE == DEFAULT_START_DATE:
                    START_DATE = dt
                else:
                    END_DATE = dt
            except ValueError:
                pass

    # If no dates provided and not explicitly set to full range by user,
    # we might want to default to 1 month for speed as per user suggestion,
    # but the instructions said "defaults range is the June 1, 2022 to June 1, 2026".
    # I will stick to the 4-year default but allow easy override.
    try:
        chain = parse_confluence_command(query_cmd)
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
