import logging
import sys
import os
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from colorama import Fore, Style, init

# Initialize colorama for cross-platform color support
init(autoreset=True)

# Define color mapping for log levels
LOG_COLORS = {
    logging.DEBUG: Fore.CYAN,
    logging.INFO: Fore.GREEN,
    logging.WARNING: Fore.YELLOW,
    logging.ERROR: Fore.RED,
    logging.CRITICAL: Fore.MAGENTA + Style.BRIGHT
}

class ColorFormatter(logging.Formatter):
    def format(self, record):
        color = LOG_COLORS.get(record.levelno, "")
        message = super().format(record)
        return f"{color}{message}{Style.RESET_ALL}"

def _is_same_file_handler(handler, path):
    base = getattr(handler, "baseFilename", None)
    if not base:
        return False
    try:
        return os.path.abspath(base) == os.path.abspath(path)
    except Exception:
        return False

def get_logger(name: str,
                level=logging.INFO,
                log_file: str = "trade_bot.log",
                max_bytes: int = 10 * 1024 * 1024,
                backup_count: int = 5,
                timed: bool = False,
                when: str = "midnight",
                interval: int = 1):
    """
    Return a named logger.

    Parameters:
    - name: logger name
    - level: desired logging level
    - log_file: if provided, add a file handler (rotating or timed)
    - max_bytes, backup_count: for RotatingFileHandler
    - timed, when, interval, backup_count: for TimedRotatingFileHandler

    Behavior:
    - Keeps existing behavior: if logger has no handlers, add colored console handler.
    - If log_file is given, add a file handler for that path (idempotent).
    - Avoids adding duplicate handlers on repeated calls.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False  # prevent double logging via root handlers

    # Ensure console handler exists (colored)
    console_present = any(isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) in (sys.stdout, sys.stderr)
                            for h in logger.handlers)
    if not console_present:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_formatter = ColorFormatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s',
                                        datefmt='%Y-%m-%d %H:%M:%S')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    else:
        # update existing console handler levels
        for h in logger.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setLevel(level)

    # If a log_file is specified, ensure a file handler exists for it (idempotent)
    if log_file:
        # ensure directory exists
        try:
            log_dir = os.path.dirname(os.path.abspath(log_file))
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
        except Exception:
            # directory creation failed, but continue to attempt to create handler (will raise later)
            pass

        # check for an existing file handler for same path
        for h in logger.handlers:
            if _is_same_file_handler(h, log_file):
                h.setLevel(level)
                return logger

        # create file handler (timed or size-rotating)
        if timed:
            fh = TimedRotatingFileHandler(log_file, when=when, interval=interval, backupCount=backup_count, encoding="utf-8")
        else:
            fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")

        fh.setLevel(level)
        file_formatter = logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s',
                                        datefmt='%Y-%m-%d %H:%M:%S')
        fh.setFormatter(file_formatter)
        logger.addHandler(fh)

    return logger