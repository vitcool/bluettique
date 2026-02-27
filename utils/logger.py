import os
import logging
from logging.handlers import TimedRotatingFileHandler

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def create_default_formatter() -> logging.Formatter:
    return logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)


def setup_logging():
    is_dev_env = os.getenv("ENV", "").lower() == "dev"
    level = logging.DEBUG if is_dev_env else logging.INFO

    folder_path = "logs"
    os.makedirs(folder_path, exist_ok=True)

    formatter = create_default_formatter()

    file_handler = TimedRotatingFileHandler(
        filename=f"{folder_path}/log.txt",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
