import logging
from logging.handlers import RotatingFileHandler
import time

import colorlog
import httpx

from configs import LOKI_URL, SYSTEM_USER


def send_loki(level: str, message: str, app: str):
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
            client.post(LOKI_URL, json=log_entry, headers=headers, timeout=2.0)
    except Exception as e:
        print(f"[send_loki error]: {e}")


class LokiHandler(logging.Handler):
    def __init__(self, app: str):
        super().__init__()
        self.app = app

    def emit(self, record):
        try:
            message = self.format(record)
            level = record.levelname.upper()
            send_loki(level, message, self.app)
        except Exception:
            self.handleError(record)


def get_logger(name: str, app: str = 'api', log_file: str = "logs/api.log") -> logging.Logger:
    """
    Создаёт и возвращает настроенный логгер с консолью и файловым логированием.

    :param name: имя логгера
    :param log_file: путь до файла логов
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Форматтер для файла
    file_formatter = logging.Formatter(
        fmt="%(name)s | %(asctime)s | %(levelname)s | %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Форматтер для консоли с цветом
    console_formatter = colorlog.ColoredFormatter(
        "%(name)s | %(log_color)s%(asctime)s | %(levelname)s | %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    )

    # Файл
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    # Консоль
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(console_formatter)

    # Создаём хендлер для Loki
    loki_handler = LokiHandler(app)
    loki_handler.setLevel(logging.DEBUG)  # или нужный уровень
    loki_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
    ))

    # Чтобы не дублировались хендлеры при повторном вызове
    if not logger.hasHandlers():
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.addHandler(loki_handler)

    return logger

logger = get_logger("CASH_SYSTEM", 'cash_system', f'/home/{SYSTEM_USER}/kso_modular_backend/logs/cash_system.log')
