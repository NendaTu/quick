import asyncio, logging, argparse, importlib.util, os, sys
from engine.core import Engine
from engine.entry import SignalRouter
from config import MODE, RISK_PER_TRADE, TARGET_NET_ROE

class DBLogHandler(logging.Handler):
    def __init__(self, db):
        super().__init__()
        self.db = db

    def emit(self, record):
        try:
            msg = self.format(record)
            self.db.save_log(record.levelname, record.name, msg)
        except Exception:
            self.handleError(record)

log = logging.getLogger("scalper")

from tools.logger import setup_logging

def load_strategy(strategy_path: str, simulator=None, overrides=None):
    """
    [TECH-001] Enhanced strategy loader with full recursive directory support.
    Calling a parent directory will now correctly load all strategies in all
    nested subdirectories.
    """
    # Normalize strategy_path - remove leading strategies/ if present
    if strategy_path.startswith("strategies/"):
        strategy_path = strategy_path[11:]
    elif strategy_path == "strategies":
        strategy_path = ""

    potential_dir = os.path.join("strategies", strategy_path)

    # 1. Directory-based Discovery (Recursive Families)
    if os.path.isdir(potential_dir):
        strategies = []
        # Support recursive discovery
        for root, dirs, files in os.walk(potential_dir):
            for f in sorted(files):
                if f.endswith(".py") and not f.startswith("__") and "base_strategy" not in f:
                    # Construct relative path for loader
                    full_f_path = os.path.join(root, f)
                    res = load_strategy(full_f_path, simulator=simulator, overrides=overrides)
                    if res:
                        if isinstance(res, list): strategies.extend(res)
                        else: strategies.append(res)
        return strategies if strategies else None

    # 2. Single File Discovery
    full_path = strategy_path
    if not os.path.exists(full_path):
        # Try relative to strategies/
        full_path = os.path.join("strategies", strategy_path)
        if not full_path.endswith(".py"):
            full_path += ".py"

    if not os.path.exists(full_path):
        # Fuzzy match in strategies/
        name = strategy_path.replace("/", ".").replace(".py", "")
        for f in os.listdir("strategies"):
            if f.startswith(name) and f.endswith(".py"):
                full_path = os.path.join("strategies", f)
                break

    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return None

    try:
        spec = importlib.util.spec_from_file_location("strategy", full_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for name, obj in module.__dict__.items():
            if isinstance(obj, type) and name != "JBaseStrategy" and "Strategy" in name:
                instance = obj(simulator=simulator, config_overrides=overrides)
                # [TECH-001] Extract strategy_id from filename (before first dot)
                base_name = os.path.basename(full_path)
                strat_id = base_name.split(".")[0]
                instance.strategy_id = strat_id
                return instance
    except Exception as e:
        log.error(f"Error loading strategy file {full_path}: {e}")

    return None

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("strategy_pos", type=str, nargs="?", default=None)
    parser.add_argument("--strategy", type=str, default=None)
    parser.add_argument("--mode", type=str, default=MODE)
    args, unknown = parser.parse_known_args()

    # Determine strategy - positional argument takes precedence
    strategy_query = args.strategy_pos or args.strategy or "scalper.1.jules"

    # Parse unknown args as config overrides
    overrides = {}
    for arg in unknown:
        if "=" in arg:
            k, v = arg.split("=", 1)
            try:
                import ast
                overrides[k] = ast.literal_eval(v)
            except:
                overrides[k] = v

    # Final configuration safety checks
    if TARGET_NET_ROE >= 1.0:
        log.warning(f"HIGH TARGET_NET_ROE DETECTED: {TARGET_NET_ROE}. This is a decimal ROE (0.05 = 5%). Please verify config.")

    engine = Engine(mode=args.mode)

    # 0. Setup Logging with DB support
    setup_logging(db=getattr(engine.exchange, 'db', None))

    # Load strategy
    strategies = load_strategy(strategy_query, simulator=engine.exchange, overrides=overrides)
    if strategies:
        if isinstance(strategies, list):
            log.info(f"Loaded Strategy Family: {strategy_query} ({len(strategies)} members)")
            engine.strategies = strategies
            # Backwards compatibility for single strategy check
            engine.strategy = strategies[0]
        else:
            log.info(f"Loaded Strategy: {strategies.name} v{strategies.version} by {strategies.author}")
            engine.strategy = strategies
            engine.strategies = [strategies]
    else:
        log.error(f"Failed to load strategy: {strategy_query}")
        return

    try:
        await engine.start()
    except asyncio.CancelledError:
        pass
    finally:
        engine._print_final_stats()

if __name__ == "__main__":
    log.info(f"Starting bot in {MODE.upper()} mode")
    log.info(f"Target net profit per trade: {RISK_PER_TRADE*100}% of equity")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot interrupted.")