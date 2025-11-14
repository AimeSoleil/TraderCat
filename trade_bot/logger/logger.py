import logging
import sys
from colorama import Fore, Style, init

# Initialize colorama for Windows compatibility
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

def get_logger(name: str, level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)

        # Use color formatter
        formatter = ColorFormatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s\n',
                                    datefmt='%Y-%m-%d %H:%M:%S')
        console_handler.setFormatter(formatter)

        logger.addHandler(console_handler)

    return logger