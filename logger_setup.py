import logging
from logging.handlers import RotatingFileHandler


def setup_logger(name, log_file, level=logging.INFO):
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    # файл (ротируемый)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # консоль
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)

    # создаём логгер
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # чтобы не дублировал, чистим хендлеры
    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console)

    # запрещаем всплытие к root
    logger.propagate = False

    return logger
