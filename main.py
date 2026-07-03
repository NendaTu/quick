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

# Configure root logger to DEBUG to capture everything for the DB
logging.getLogger().setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# Console handler (Only INFO and above)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logging.getLogger().addHandler(console_handler)
log = logging.getLogger("scalper")

def load_strategy(strategy_path: str, simulator=None, overrides=None):
    if not strategy_path.endswith(".py"):
        # Discovery mechanism
        name = strategy_path.replace("/", ".")
        strategy_path = f"strategies/{name}.py"
        if not os.path.exists(strategy_path):
            # Try to find it
            for f in os.listdir("strategies"):
                if f.startswith(name) and f.endswith(".py"):
                    strategy_path = f"strategies/{f}"
                    break

    spec = importlib.util.spec_from_file_location("strategy", strategy_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Expecting a class that inherits from JBaseStrategy
    # We'll look for a class that isn't JBaseStrategy itself
    for name, obj in module.__dict__.items():
        if isinstance(obj, type) and name != "JBaseStrategy" and "Strategy" in name:
            return obj(simulator=simulator, config_overrides=overrides)
    return None

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", type=str, default="scalper.1.jules")
    parser.add_argument("--mode", type=str, default=MODE)
    args, unknown = parser.parse_known_args()

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

    engine = Engine()

    # Load strategy
    strategy = load_strategy(args.strategy, simulator=engine.exchange, overrides=overrides)
    if strategy:
        log.info(f"Loaded Strategy: {strategy.name} v{strategy.version} by {strategy.author}")
        engine.strategy = strategy
    else:
        log.error(f"Failed to load strategy: {args.strategy}")
        return

    # Add DB logging
    if hasattr(engine.exchange, "db"):
        db_handler = DBLogHandler(engine.exchange.db)
        db_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
        logging.getLogger().addHandler(db_handler)

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