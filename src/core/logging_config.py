"""Konfiguracja centralnego loggera aplikacji zapisującego do pliku companyVerificator.log."""

import logging
import sys

from src.config import LOG_FILE_PATH

_logger_initialized = False


def setup_app_logging() -> logging.Logger:
    """Inicjalizuje główny logger aplikacji zapisujący do companyVerificator.log i na stdout."""
    global _logger_initialized
    logger = logging.getLogger("company_verificator")

    if _logger_initialized:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. Zapis do pliku companyVerificator.log
    try:
        LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(LOG_FILE_PATH), encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as exc:
        print(f"WARN: Nie udało się utworzyć pliku logów {LOG_FILE_PATH}: {exc}", file=sys.stderr)

    # 2. Konsola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    _logger_initialized = True
    return logger


app_logger = setup_app_logging()
