import asyncio
import signal
from dotenv import load_dotenv
from controllers.fingerbot import FingerBotController
from controllers.tapo import TapoController
from controllers.bluetti import BluettiController
from state_handler import SystemState, handle_state


async def main(tapo_controller, bluetti_controller, fingerbot_controller):
    await tapo_controller.initialize()
    await bluetti_controller.initialize()

    def handle_interrupt(signal, frame):
        print("KeyboardInterrupt received, stopping services...")
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
