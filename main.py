import asyncio, logging
from engine import Engine
from config import MODE, RISK_PER_TRADE

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

async def main():
    engine = Engine()

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