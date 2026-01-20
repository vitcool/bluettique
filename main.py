import asyncio
import signal
import logging
import os
from dotenv import load_dotenv
from controllers.bluetti import BluettiController
from controllers.tapo import TapoController
from utils.logger import setup_logging
from charging_state_handler import ChargingStateHandler

async def test_bluetti_dc_cycle(bluetti_controller: BluettiController):
    """Initialize Bluetti, pulse DC on/off without powering the unit down."""
    await bluetti_controller.initialize()
    if not bluetti_controller.connection_set:
        logging.info("Bluetti connection failed; skipping DC cycle test.")
        return

    logging.info("Turning Bluetti DC output ON for 10 seconds...")
    bluetti_controller.turn_dc("ON")
    await asyncio.sleep(10)
    logging.info("Turning Bluetti DC output OFF; leaving device powered on.")
    bluetti_controller.turn_dc("OFF")
    bluetti_controller.stop()


async def main(tapo_controller, bluetti_controller):
    setup_logging()

    logging.info("Starting Bluetti DC cycle test...")
    print("Starting Bluetti DC cycle test...")

    def handle_stop_signal(signum, frame):
        logging.info("Stop signal received, performing cleanup...")
        bluetti_controller.stop()
        logging.info("Cleanup complete, exiting.")
        exit(0)

    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_stop_signal)
    signal.signal(signal.SIGINT, handle_stop_signal)

    await test_bluetti_dc_cycle(bluetti_controller)

    # Original state machine loop commented out for Bluetti testing
    # charging_handler = ChargingStateHandler(tapo_controller)
    # while True:
    #     await charging_handler.handle_state()


load_dotenv()

asyncio.run(main(TapoController(), BluettiController()))
