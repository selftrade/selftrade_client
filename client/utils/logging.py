# client/utils/logging.py - Client logging configuration
import logging
import sys
from logging.handlers import RotatingFileHandler

from client.config import LOG_FILE, LOG_LEVEL, LOG_FORMAT


def setup_logging(log_file: str = None, log_level: str = None) -> logging.Logger:
    """
    Setup logging for the client application.

    Args:
        log_file: Override log file path
        log_level: Override log level

    Returns:
        Configured root logger
    """
    log_file = log_file or LOG_FILE
    log_level = log_level or LOG_LEVEL

    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Clear existing handlers
    logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler with rotation
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(LOG_FORMAT)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not setup file logging: {e}")

    return logger


class LogCapture:
    """Capture logs for display in UI"""

    def __init__(self, max_lines: int = 1000):
        self.lines = []
        self.max_lines = max_lines
        self.handlers = []

    def start_capture(self):
        """Start capturing logs"""
        handler = LogCaptureHandler(self)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S'))
        logging.getLogger().addHandler(handler)
        self.handlers.append(handler)

    def stop_capture(self):
        """Stop capturing logs"""
        for handler in self.handlers:
            logging.getLogger().removeHandler(handler)
        self.handlers.clear()

    def add_line(self, line: str):
        """Add a log line"""
        self.lines.append(line)
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]

    def get_lines(self) -> list:
        """Get captured log lines"""
        return self.lines.copy()

    def clear(self):
        """Clear captured lines"""
        self.lines.clear()


class LogCaptureHandler(logging.Handler):
    """Custom handler to capture logs"""

    def __init__(self, capture: LogCapture):
        super().__init__()
        self.capture = capture

    def emit(self, record):
        try:
            msg = self.format(record)
            self.capture.add_line(msg)
        except Exception:
            self.handleError(record)
