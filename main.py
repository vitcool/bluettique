import asyncio
import signal
from dotenv import load_dotenv
from fingerbotController import FingerBotController
from tapoController import TapoController
from bluettiController import BluettiController
from enum import Enum, auto
from bluetti_utils import fetch_bluetti_status
from state_handler import SystemState, handle_state


async def main(tapoController, bluettiController, fingerbotController):
    await tapoController.initialize()
    await bluettiController.initialize()

    def handle_interrupt(signal, frame):
        print("KeyboardInterrupt received, stopping services...")
        bluettiController.stop()
        exit(0)

    signal.signal(signal.SIGINT, handle_interrupt)

    current_state = SystemState.INITIAL_CHECK

    while True:
        current_state = await handle_state(
            current_state, tapoController, bluettiController, fingerbotController
        )
        await asyncio.sleep(1)


load_dotenv()

asyncio.run(main(TapoController(), BluettiController(), FingerBotController()))
