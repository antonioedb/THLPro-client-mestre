from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler


def configure_logging(log_file: str, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("thlpro_client")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(threadName)s - %(message)s")

    file_handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger
