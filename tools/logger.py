import logging
import sys
import os
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

class Tee:
    def __init__(self, original_stream, filepath):
        self.original_stream = original_stream
        self.filepath = filepath
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        # Use append mode "a" to allow stdout and stderr streams to write concurrently without clobbering each other.
        self.file = open(filepath, "a", encoding="utf-8", buffering=1)

    def write(self, data):
        self.original_stream.write(data)
        # Skip carriage returns and progress bar updates in the file log to prevent bloating
        if "\r" not in data:
            self.file.write(data)

    def flush(self):
        self.original_stream.flush()
        self.file.flush()

    def close(self):
        try:
            self.file.close()
        except:
            pass

def setup_console_tee(console_log_path="docs/temp/console-log.txt"):
    """
    Redirects stdout and stderr streams to capture all console outputs
    to the specified file, using the Tee class.
    Returns: stdout_tee, stderr_tee
    """
    os.makedirs(os.path.dirname(console_log_path), exist_ok=True)
    with open(console_log_path, "w", encoding="utf-8") as f:
        pass

    stdout_tee = Tee(sys.stdout, console_log_path)
    stderr_tee = Tee(sys.stderr, console_log_path)
    sys.stdout = stdout_tee
    sys.stderr = stderr_tee
    return stdout_tee, stderr_tee

def setup_metrics_logging(start_time: float, symbol: str, side: str, strategy_id: str, scoring_result: dict, log_dir="docs/temp"):
    """
    Centralized writer for the metrics-log.txt file.
    """
    os.makedirs(log_dir, exist_ok=True)
    start_dt = datetime.fromtimestamp(start_time).strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(log_dir, f"{start_dt}.metrics-log.txt")

    keys = ["rsi", "rsi_ceiling", "imbalance", "macd", "trend_15m", "supertrend", "drt", "sanity", "btc_mom", "btc_conf", "htf_bias", "structure", "vol_influx", "atr", "spread", "vol_pct", "confidence"]

    if not os.path.exists(filepath):
        header = ["timestamp", "symbol", "target_side", "strategy_id"]
        for k in keys:
            header.append(f"{k}_raw")
            header.append(f"{k}_weighted")
        header.extend(["aggregated_score", "entry_threshold", "decision", "rejection_reason"])
        with open(filepath, "w") as f:
            f.write(",".join(header) + "\n")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    row = [now_str, symbol, side, strategy_id]
    raw_scores = scoring_result.get("raw_scores", {})
    weighted_scores = scoring_result.get("weighted_scores", {})
    for k in keys:
        raw_val = raw_scores.get(k, 0.0)
        weighted_val = weighted_scores.get(k, 0.0)
        row.append(f"{raw_val:.4f}")
        row.append(f"{weighted_val:.4f}")
    row.extend([
        f"{scoring_result.get('aggregated_score', 0.0):.4f}",
        f"{scoring_result.get('entry_threshold', 30.0):.4f}",
        scoring_result.get("decision", "REJECTED"),
        scoring_result.get("reason", "").replace(",", ";")
    ])
    with open(filepath, "a") as f:
        f.write(",".join(row) + "\n")

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
