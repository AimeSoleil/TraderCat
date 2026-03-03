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

# ── Default log file paths ────────────────────────────────────────────
DEFAULT_LOG_DIR = "logs"
DEFAULT_API_LOG_FILE = "logs/api.log"
DEFAULT_PIPELINE_LOG_FILE = "logs/pipeline.log"
DEFAULT_LLM_LOG_FILE = "logs/llm_calls.log"

# Prefix → default log file.  Evaluated in order; first match wins.
_PREFIX_LOG_MAP: list[tuple[str, str]] = [
    ("tradercat.ai.llm_calls", DEFAULT_LLM_LOG_FILE),
    ("tradercat.pipeline",     DEFAULT_PIPELINE_LOG_FILE),
    ("tradercat.core",         DEFAULT_PIPELINE_LOG_FILE),
    ("tradercat.ai",           DEFAULT_PIPELINE_LOG_FILE),
    ("tradercat.api",          DEFAULT_API_LOG_FILE),
    ("tradercat.main",         DEFAULT_API_LOG_FILE),
    ("tradercat.database",     DEFAULT_API_LOG_FILE),
]

_DEFAULT_FALLBACK_LOG = DEFAULT_API_LOG_FILE


def _resolve_default_log_file(name: str) -> Optional[str]:
    """Return the default log file for *name*, or None for non-tradercat loggers."""
    for prefix, path in _PREFIX_LOG_MAP:
        if name == prefix or name.startswith(prefix + "."):
            return path
    if name.startswith("tradercat."):
        return _DEFAULT_FALLBACK_LOG
    return None


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


def _ensure_dir(file_path: str) -> None:
    """Create parent directories for *file_path* if they don't exist."""
    try:
        log_dir = os.path.dirname(os.path.abspath(file_path))
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
    except Exception:
        pass


def _add_file_handler(
    lgr: logging.Logger,
    log_file: str,
    level: int,
    use_json: bool,
    timed: bool = False,
    when: str = "midnight",
    interval: int = 1,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Attach a rotating file handler to *lgr* for *log_file* (idempotent).

    If a handler for the same path already exists **and** has the same
    rotation type, just update its level.  If the rotation type differs
    (e.g. caller requests timed but the existing handler is size-based),
    replace the old handler so the caller gets the requested behaviour.
    """
    desired_cls = TimedRotatingFileHandler if timed else RotatingFileHandler

    for h in lgr.handlers:
        if _is_same_file_handler(h, log_file):
            if isinstance(h, desired_cls):
                # Same path, same type → nothing to do
                h.setLevel(level)
                return
            if not timed and isinstance(h, TimedRotatingFileHandler):
                # Caller wants size-rotating but a timed handler is already
                # attached (i.e. init_llm_logger upgraded it).  Keep the
                # timed handler — don't downgrade.
                h.setLevel(level)
                return
            # Same path but wrong type → remove so we can re-create below
            lgr.removeHandler(h)
            h.close()
            break

    _ensure_dir(log_file)

    if timed:
        fh = TimedRotatingFileHandler(
            log_file, when=when, interval=interval,
            backupCount=backup_count, encoding="utf-8",
        )
    else:
        fh = RotatingFileHandler(
            log_file, maxBytes=max_bytes,
            backupCount=backup_count, encoding="utf-8",
        )

    fh.setLevel(level)
    if use_json:
        fh.setFormatter(JSONFormatter())
    else:
        fh.setFormatter(logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        ))
    lgr.addHandler(fh)


def get_logger(name: str,
                level: Optional[int] = None,
                log_file: Optional[str] = None,
                max_bytes: int = 10 * 1024 * 1024,
                backup_count: int = 5,
                timed: bool = False,
                when: str = "midnight",
                interval: int = 1,
                use_json: Optional[bool] = None,
                disable_file: bool = False):
    """
    Return a named logger with **both** console and file output.

    When ``level`` or ``use_json`` are not provided they are read
    automatically from ``tradercat.config.settings`` (log_level /
    log_format).  This allows callers to simply write::

        from tradercat.logger import get_logger
        logger = get_logger(__name__)

    File-handler behaviour:

    * If *log_file* is given explicitly, that path is used.
    * Otherwise a default is chosen based on the logger **name**:

      - ``tradercat.api.*`` / ``tradercat.main`` → ``logs/api.log``
      - ``tradercat.pipeline.*`` / ``tradercat.core.*`` / ``tradercat.ai.*``
        → ``logs/pipeline.log``
      - ``tradercat.ai.llm_calls`` → ``logs/llm_calls.log``

    * Pass ``disable_file=True`` to skip the file handler entirely.
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

    # ── Console handler (stdout) ──
    console_present = any(
        isinstance(h, logging.StreamHandler)
        and getattr(h, "stream", None) in (sys.stdout, sys.stderr)
        for h in logger.handlers
    )
    if not console_present:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)
        if use_json:
            ch.setFormatter(JSONFormatter())
        else:
            ch.setFormatter(ColorFormatter(
                '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S',
            ))
        logger.addHandler(ch)
    else:
        for h in logger.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setLevel(level)

    # ── File handler (auto-resolved or explicit) ──
    if not disable_file:
        resolved = log_file or _resolve_default_log_file(name)
        if resolved:
            _add_file_handler(
                logger, resolved, level, use_json,
                timed=timed, when=when, interval=interval,
                max_bytes=max_bytes, backup_count=backup_count,
            )

    return logger


def init_llm_logger(log_file: Optional[str] = None, use_json: bool = True) -> None:
    """
    Initialize the dedicated LLM call logger with a timed-rotating file handler.

    Should be called once during startup (from ``main.py`` or ``runner.py``).
    With the refactored ``get_logger`` the LLM logger already gets a
    size-rotating handler automatically; calling this upgrades it to a
    timed-rotating (daily) handler.
    """
    if log_file is None:
        try:
            from tradercat.config import settings as _settings
            log_file = _settings.llm_progress_log_file
        except Exception:
            log_file = DEFAULT_LLM_LOG_FILE

    get_logger(
        "tradercat.ai.llm_calls",
        level=logging.INFO,
        log_file=log_file,
        use_json=use_json,
        timed=True,
        when="midnight",
    )
