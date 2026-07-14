import logging
import sys
from datetime import datetime
import pytz

# VIRTUAL_TIME: Tracked globally during backtests and simulation to prefix console logs with virtual dates.
VIRTUAL_TIME = None

class VirtualTimeFormatter(logging.Formatter):
    """
    Custom logging formatter that dynamically appends the active backtest virtual time
    as [YYYY-MM-DD HH:MM:SS] next to the real-time system clock prefix.
    """
    def format(self, record):
        global VIRTUAL_TIME
        if VIRTUAL_TIME is not None:
            # Convert virtual timestamp to readable UTC date-time
            dt_str = datetime.fromtimestamp(VIRTUAL_TIME, tz=pytz.UTC).strftime("%Y-%m-%d %H:%M:%S")
            orig_asctime = self.formatTime(record, self.datefmt)
            prefix = f"{orig_asctime} [{dt_str}]"
            formatted_msg = super().format(record)
            if formatted_msg.startswith(orig_asctime):
                return prefix + formatted_msg[len(orig_asctime):]
            return f"[{dt_str}] " + formatted_msg
        return super().format(record)

def setup_logging(db=None, level=logging.INFO):
    """
    [TECH-001] Centralized logging setup to prevent global escalation
    and duplicate handlers across main, backtest, and compare.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG) # Always capture DEBUG for potentially the DB

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # Use our custom VirtualTimeFormatter
    formatter = VirtualTimeFormatter("%(asctime)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # Hard-enforce console silence for heavy loggers
    logging.getLogger("backtest").setLevel(level)
    logging.getLogger("downloader").setLevel(level)
    logging.getLogger("scalper.database").setLevel(logging.INFO)
    logging.getLogger("scalper.engine").setLevel(logging.INFO)

    if db:
        from main import DBLogHandler
        db_handler = DBLogHandler(db)
        db_handler.setFormatter(formatter)
        root.addHandler(db_handler)

    # Suppress internal system noise from console
    logging.getLogger("scalper.models").setLevel(logging.WARNING)
    logging.getLogger("scalper.simulator").setLevel(logging.INFO)
    logging.getLogger("scalper.engine").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
