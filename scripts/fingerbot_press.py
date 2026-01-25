import asyncio
import logging
import os
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler

from dotenv import load_dotenv

# Ensure project root is on import path when running as a script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controllers.fingerbot import FingerBotController


REQUIRED_ENV_VARS = [
    "FINGERBOT_LOCAL_KEY_MAIN",
    "FINGERBOT_MAC_MAIN",
    "FINGERBOT_UUID_MAIN",
    "FINGERBOT_DEV_ID_MAIN",
]


def validate_env():
    missing = [key for key in REQUIRED_ENV_VARS if not os.getenv(key)]
    if missing:
        raise SystemExit(f"Missing required FingerBot env vars: {', '.join(missing)}")


def setup_experiment_logging():
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logfile = log_dir / "fingerbot_press.log"

    handler = TimedRotatingFileHandler(
        filename=logfile,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    # Also log to stdout for quick feedback
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(logging.INFO)
    root_logger.addHandler(console)


async def main():
    load_dotenv()
    setup_experiment_logging()
    validate_env()

    logging.info("FingerBot (host): connecting to main device and pressing button")

    controller = FingerBotController()
    await controller.press_button(press_additional=False)

    logging.info("FingerBot (host): completed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("FingerBot (host): interrupted by user")
