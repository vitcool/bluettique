import asyncio
import signal
import logging
import os
from dotenv import load_dotenv
from controllers.fingerbot import FingerBotController
from controllers.tapo import TapoController
from controllers.bluetti import BluettiController
from state_handler import SystemState, handle_state


async def main(tapo_controller, bluetti_controller, fingerbot_controller):
    is_dev_env = os.getenv("ENV") == "dev"
    folder_path = 'logs'
    
    os.makedirs(folder_path, exist_ok=True)
    
    logging.basicConfig(
        filename=f'{folder_path}/log.txt',
        level=logging.DEBUG if is_dev_env else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )
    
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
