import sys
import time
import threading
import itertools
from tradercat.logger.logger import get_logger

# 获取项目的 logger
logger = get_logger(__name__)

class LoadingSpinner:
    """
    A simple thread-based spinner/loader for console feedback.
    """
    def __init__(self, message="Processing", delay=0.1):
        self.message = message
        self.delay = delay
        self.stop_event = threading.Event()
        self.thread = None
        # Spinner characters: | / - \
        self.spinner = itertools.cycle(['|', '/', '-', '\\'])

    def _spin(self):
        """
        Use sys.stdout for animation because loggers add newlines (\n) 
        and timestamps which break the inline animation effect.
        """
        while not self.stop_event.is_set():
            sys.stdout.write(f"\r{self.message} {next(self.spinner)} ")
            sys.stdout.flush()
            time.sleep(self.delay)
            # Backspace to clear the spinner character for the next frame
            # len(message) + space + char + space = len + 3
            sys.stdout.write("\b" * (len(self.message) + 3))

    def start(self):
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._spin)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()
        
        # 1. Clear the animation line completely from the console
        # Overwrite with spaces, then return carriage
        sys.stdout.write(f"\r{' ' * (len(self.message) + 5)}\r")
        sys.stdout.flush()

        # 2. Use logger for the final persistent record
        # This ensures "Done" appears in your log files and console history properly
        logger.info(f"{self.message} Done!")