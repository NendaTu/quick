import logging
import sys
from typing import Optional

def setup_logging(db=None, level=logging.INFO):
    """
    [TECH-001] Centralized logging setup to prevent global escalation
    and duplicate handlers across main, backtest, and compare.
    """
    # Configure root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG) # Always capture DEBUG for potentially the DB

    # Remove existing handlers to prevent duplicates
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

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

    # DB handler if provided
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
