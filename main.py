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
    """Initialize Bluetti, then toggle DC on/off five times with 5s intervals."""
    await bluetti_controller.initialize()
    if not bluetti_controller.connection_set:
        logging.info("Bluetti connection failed; skipping DC cycle test.")
        return

    cycles = 5
    for i in range(1, cycles + 1):
        logging.info(f"[Cycle {i}/{cycles}] Turning Bluetti DC output ON")
        bluetti_controller.turn_dc("ON")
        await asyncio.sleep(5)
        logging.info(f"[Cycle {i}/{cycles}] Turning Bluetti DC output OFF")
        bluetti_controller.turn_dc("OFF")
        await asyncio.sleep(5)

    # After the test cycles, gracefully stop MQTT client/broker so the adapter is freed.
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
