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
    t110_online = False
    t110_charging = False
    tapo_initial_sucess = await tapoController.initialize()

    def handle_interrupt(signal, frame):
        print("KeyboardInterrupt received, stopping services...")
        bluettiController.stop()
        exit(0)

    signal.signal(signal.SIGINT, handle_interrupt)

    if not tapo_initial_sucess:
        print("Failed to initialize Tapo controller")

    while not await bluettiController.initialize():
        print("Failed to initialize Bluetooth controller")
        await fingerbotController.press_button()

    current_state = SystemState.IDLE
    
    while True:
        current_state = await handle_state(current_state, tapoController, bluettiController, fingerbotController)
        await asyncio.sleep(1)

load_dotenv()

asyncio.run(main(TapoController(), BluettiController(), FingerBotController()))
