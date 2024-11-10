import logging
import os

def setup_logging():
    is_dev_env = os.getenv("ENV") == "dev"
    folder_path = 'logs'
    os.makedirs(folder_path, exist_ok=True)
    
    logging.basicConfig(
        filename=f'{folder_path}/log.txt',
        level=logging.DEBUG if is_dev_env else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )