import asyncio
import signal
import logging
import os
from dotenv import load_dotenv
from controllers.fingerbot import FingerBotController
from controllers.tapo import TapoController
from controllers.bluetti import BluettiController
from state_handler import SystemState, StateHandler
from utils.logger import setup_logging


async def main(tapo_controller, bluetti_controller, fingerbot_controller):
    setup_logging()
    
    logging.info("Starting services...")
    print("Starting services...")

    await tapo_controller.initialize()
    await bluetti_controller.initialize()

    def handle_stop_signal(signum, frame):
        logging.info("Stop signal received, performing cleanup...")
        # Perform your cleanup logic here, e.g., stop services
        bluetti_controller.stop()
        logging.info("Cleanup complete, exiting.")
        exit(0)

    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_stop_signal)
    signal.signal(signal.SIGINT, handle_stop_signal)

    state_handler = StateHandler()

    current_state = SystemState.INITIAL_CHECK

    while True:
        current_state = await state_handler.handle_state(
            current_state, tapo_controller, bluetti_controller, fingerbot_controller
        )
        await asyncio.sleep(1)


load_dotenv()

asyncio.run(main(TapoController(), BluettiController(), FingerBotController()))
