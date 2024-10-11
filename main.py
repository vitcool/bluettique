import asyncio
import signal
from dotenv import load_dotenv
from fingerbotController import FingerBotController
from tapoController import TapoController
from bluettiController import BluettiController


async def main():
    load_dotenv()

#    fingerbotController = FingerBotController()
#    await fingerbotController.press_button()

    #tapoController = TapoController()
    #await tapoController.initialize()
    #await tapoController.turn_on()
    #await asyncio.sleep(2)  # Simulate some delay
    #await tapoController.turn_off()

    bluetiiController = BluettiController()

    def handle_interrupt(signal, frame):
        print("KeyboardInterrupt received, stopping services...")
        bluetiiController.stop()
        exit(0)

    # Register the signal handler for KeyboardInterrupt
    signal.signal(signal.SIGINT, handle_interrupt)

    await bluetiiController.initialize()
    await asyncio.sleep(2)
    bluetiiController.turn_dc()

    # Keep the service running
    while True:
        pass



asyncio.run(main())
