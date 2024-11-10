import asyncio
import signal
import logging
import os
from dotenv import load_dotenv
from controllers.fingerbot import FingerBotController
from controllers.tapo import TapoController
from controllers.bluetti import BluettiController
from state_handler import SystemState, handle_state
from utils.logger import setup_logging


async def main(tapo_controller, bluetti_controller, fingerbot_controller):
    setup_logging()
    
    logging.info("Starting services...")

    await tapo_controller.initialize()
    await bluetti_controller.initialize()

    def handle_interrupt(signal, frame):
        logging.info("KeyboardInterrupt received, stopping services...")
        bluetti_controller.stop()
        exit(0)

    signal.signal(signal.SIGINT, handle_interrupt)

    current_state = SystemState.INITIAL_CHECK

    while True:
        current_state = await handle_state(
            current_state, tapo_controller, bluetti_controller, fingerbot_controller
        )
        await asyncio.sleep(1)


load_dotenv()

asyncio.run(main(TapoController(), BluettiController(), FingerBotController()))
