import logging
import sys
import os
import json
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Optional

try:
    from colorama import Fore, Style, init
    # Initialize colorama for cross-platform color support
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False
    Fore = Style = type('Mock', (), {'__getattr__': lambda self, name: ''})()

# Define color mapping for log levels
LOG_COLORS = {
    logging.DEBUG: Fore.CYAN if COLORAMA_AVAILABLE else "",
    logging.INFO: Fore.GREEN if COLORAMA_AVAILABLE else "",
    logging.WARNING: Fore.YELLOW if COLORAMA_AVAILABLE else "",
    logging.ERROR: Fore.RED if COLORAMA_AVAILABLE else "",
    logging.CRITICAL: (Fore.MAGENTA + Style.BRIGHT) if COLORAMA_AVAILABLE else ""
}


class JSONFormatter(logging.Formatter):
    """Structured JSON logging formatter."""
    
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add extra fields if present
        if hasattr(record, "user_id"):
            log_entry["user_id"] = record.user_id
        if hasattr(record, "symbol"):
            log_entry["symbol"] = record.symbol
        if hasattr(record, "strategy"):
            log_entry["strategy"] = record.strategy
        
        # Add LLM-specific fields if present
        if hasattr(record, "llm_event"):
            log_entry["llm_event"] = record.llm_event
        if hasattr(record, "role"):
            log_entry["role"] = record.role
        if hasattr(record, "model"):
            log_entry["model"] = record.model
        if hasattr(record, "elapsed_seconds"):
            log_entry["elapsed_seconds"] = record.elapsed_seconds
        if hasattr(record, "system_prompt_length"):
            log_entry["system_prompt_length"] = record.system_prompt_length
        if hasattr(record, "user_prompt_length"):
            log_entry["user_prompt_length"] = record.user_prompt_length
        if hasattr(record, "output_length"):
            log_entry["output_length"] = record.output_length
        if hasattr(record, "identity"):
            log_entry["identity"] = record.identity
        if hasattr(record, "phase"):
            log_entry["phase"] = record.phase
        if hasattr(record, "status"):
            log_entry["status"] = record.status
        
        # Add token usage fields if present
        if hasattr(record, "input_tokens"):
            log_entry["input_tokens"] = record.input_tokens
        if hasattr(record, "output_tokens"):
            log_entry["output_tokens"] = record.output_tokens
        if hasattr(record, "total_tokens"):
            log_entry["total_tokens"] = record.total_tokens
        if hasattr(record, "token_source"):
            log_entry["token_source"] = record.token_source
            
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_entry)


class ColorFormatter(logging.Formatter):
    def format(self, record):
        color = LOG_COLORS.get(record.levelno, "")
        message = super().format(record)
        reset = Style.RESET_ALL if COLORAMA_AVAILABLE else ""
        return f"{color}{message}{reset}"

def _is_same_file_handler(handler, path):
    base = getattr(handler, "baseFilename", None)
    if not base:
        return False
    try:
        return os.path.abspath(base) == os.path.abspath(path)
    except Exception:
        return False

def get_logger(name: str,
                level: Optional[int] = None,
                log_file: Optional[str] = None,
                max_bytes: int = 10 * 1024 * 1024,
                backup_count: int = 5,
                timed: bool = False,
                when: str = "midnight",
                interval: int = 1,
                use_json: Optional[bool] = None):
    """
    Return a named logger.

    When ``level`` or ``use_json`` are not provided they are read
    automatically from ``tradercat.config.settings`` (log_level /
    log_format).  This allows callers to simply write::

        from tradercat.logger import get_logger
        logger = get_logger(__name__)

    Parameters:
    - name: logger name
    - level: desired logging level (default: from settings.log_level)
    - log_file: if provided, add a file handler (rotating or timed)
    - max_bytes, backup_count: for RotatingFileHandler
    - timed, when, interval, backup_count: for TimedRotatingFileHandler
    - use_json: if True, use JSON formatting (default: from settings.log_format)

    Behavior:
    - Keeps existing behavior: if logger has no handlers, add colored console handler.
    - If log_file is given, add a file handler for that path (idempotent).
    - Avoids adding duplicate handlers on repeated calls.
    """
    # Lazy-import settings to avoid circular imports
    if level is None or use_json is None:
        from tradercat.config import settings as _settings
        if level is None:
            level = getattr(logging, _settings.log_level, logging.INFO)
        if use_json is None:
            use_json = _settings.log_format == "json"
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False  # prevent double logging via root handlers

    # Ensure console handler exists
    console_present = any(isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) in (sys.stdout, sys.stderr)
                            for h in logger.handlers)
    if not console_present:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        
        if use_json:
            console_formatter = JSONFormatter()
        else:
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


def init_llm_logger(log_file: Optional[str] = None, use_json: bool = True) -> None:
    """
    Initialize the dedicated LLM call logger.
    
    This function sets up a separate logger for LLM-specific events with a file handler.
    Should be called once during application initialization, typically from main or orchestrator.
    
    Args:
        log_file: Path to LLM call log file (if None, uses default from config)
        use_json: Whether to use JSON formatting for LLM logs
    """
    if log_file is None:
        try:
            from tradercat.config import settings as _settings
            log_file = _settings.llm_progress_log_file
        except Exception:
            log_file = "logs/llm_calls.log"
    
    # Get the LLM logger with file handler
    llm_logger = get_logger(
        "tradercat.ai.llm_calls",
        level=logging.INFO,
        log_file=log_file,
        use_json=use_json,
        timed=True,
        when="midnight"
    )
