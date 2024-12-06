import os
import logging
from logging.handlers import TimedRotatingFileHandler

def setup_logging():
    is_dev_env = os.getenv("ENV") == "dev"
    folder_path = 'logs'
    os.makedirs(folder_path, exist_ok=True)
    
    log_handler = TimedRotatingFileHandler(
        filename=f'{folder_path}/log.txt',
        when="midnight",
        interval=1,
        backupCount=7,  # Keeps logs of the last 7 days
        encoding="utf-8"
    )
    
    # Define the log format
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    formatter = logging.Formatter(log_format)
    log_handler.setFormatter(formatter)
    
    # Set the logging level
    log_handler.setLevel(logging.DEBUG if is_dev_env else logging.INFO)
    
    # Add the handler to the root logger
    logging.getLogger().addHandler(log_handler)

    # Configure basic logging for other parts of the app
    logging.basicConfig(
        level=logging.DEBUG if is_dev_env else logging.INFO,
        format=log_format
    )