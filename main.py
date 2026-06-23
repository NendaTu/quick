import asyncio, logging
from engine import Engine
from config import MODE, RISK_PER_TRADE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("scalper")

async def main():
    engine = Engine()
    await engine.start()

if __name__ == "__main__":
    log.info(f"Starting bot in {MODE.upper()} mode")
    log.info(f"Target net profit per trade: {RISK_PER_TRADE*100}% of equity")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot interrupted.")