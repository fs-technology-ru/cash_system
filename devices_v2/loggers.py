"""
Logging configuration for the cash system.

This module provides a centralized logging setup with support for:
- Console output with colored formatting
- File rotation with size limits
- Remote logging to Loki
"""

import logging
import time
from logging.handlers import RotatingFileHandler
from typing import Final

import colorlog
import httpx

from configs import LOKI_URL, SYSTEM_USER


# =============================================================================
# Constants
# =============================================================================

DEFAULT_LOG_FORMAT: Final[str] = (
    "%(name)s | %(asctime)s | %(levelname)s | %(funcName)s:%(lineno)d | %(message)s"
)
DEFAULT_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
MAX_LOG_FILE_SIZE: Final[int] = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT: Final[int] = 3
LOKI_TIMEOUT: Final[float] = 2.0


# =============================================================================
# Color Configuration
# =============================================================================

LOG_COLORS: Final[dict[str, str]] = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "bold_red",
}


# =============================================================================
# Loki Integration
# =============================================================================

def send_to_loki(level: str, message: str, app: str) -> None:
    """
    Send a log entry to Loki.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        message: Log message.
        app: Application name for Loki labels.
    """
    try:
        log_entry = {
            "streams": [
                {
                    "stream": {"level": level, "app": app},
                    "values": [[str(int(time.time() * 1e9)), message]],
                }
            ]
        }
        headers = {"Content-Type": "application/json"}
        with httpx.Client() as client:
            client.post(LOKI_URL, json=log_entry, headers=headers, timeout=LOKI_TIMEOUT)
    except Exception as e:
        # Avoid recursive logging - just print to stderr
        print(f"[Loki send error]: {e}")


class LokiHandler(logging.Handler):
    """
    Custom logging handler that sends logs to Loki.

    Attributes:
        app: Application name for Loki labels.
    """

    def __init__(self, app: str) -> None:
        """
        Initialize the Loki handler.

        Args:
            app: Application name for Loki labels.
        """
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record to Loki.

        Args:
            record: The log record to send.
        """
        try:
            message = self.format(record)
            level = record.levelname.upper()
            send_to_loki(level, message, self.app)
        except Exception:
            self.handleError(record)


# =============================================================================
# Logger Factory
# =============================================================================

def get_logger(
    name: str,
    app: str = "api",
    log_file: str = "logs/api.log",
    level: int = logging.DEBUG,
) -> logging.Logger:
    """
    Create and configure a logger with console, file, and Loki handlers.

    Args:
        name: Logger name.
        app: Application name for Loki labels.
        log_file: Path to the log file.
        level: Logging level (default: DEBUG).

    Returns:
        Configured logger instance.
    """
    logger_instance = logging.getLogger(name)
    logger_instance.setLevel(level)

    # Avoid duplicate handlers on repeated calls
    if logger_instance.hasHandlers():
        return logger_instance

    # File formatter
    file_formatter = logging.Formatter(
        fmt=DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_DATE_FORMAT,
    )

    # Console formatter with colors
    console_formatter = colorlog.ColoredFormatter(
        f"%(name)s | %(log_color)s%(asctime)s | %(levelname)s | "
        f"%(funcName)s:%(lineno)d | %(message)s",
        datefmt=DEFAULT_DATE_FORMAT,
        log_colors=LOG_COLORS,
    )

    # Loki formatter
    loki_formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
        datefmt=DEFAULT_DATE_FORMAT,
    )

    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=MAX_LOG_FILE_SIZE,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(file_formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)

    # Loki handler
    loki_handler = LokiHandler(app)
    loki_handler.setLevel(level)
    loki_handler.setFormatter(loki_formatter)

    # Add all handlers
    logger_instance.addHandler(file_handler)
    logger_instance.addHandler(console_handler)
    logger_instance.addHandler(loki_handler)

    return logger_instance


# =============================================================================
# Default Logger Instance
# =============================================================================

logger = get_logger(
    name="CASH_SYSTEM",
    app="cash_system",
    log_file=f"/home/{SYSTEM_USER}/kso_modular_backend/logs/cash_system.log",
)
