import logging
import os

def setup_logging():
    folder_path = os.path.join(os.getcwd(), 'logs')
    os.makedirs(folder_path, exist_ok=True)
    logging.basicConfig(
        filename=f'{folder_path}/log.txt',
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.info("Test log message.")

if __name__ == "__main__":
    setup_logging()
