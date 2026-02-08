import asyncio
import signal
import logging
import os
import threading
from dotenv import load_dotenv
from controllers.bluetti import BluettiController
from controllers.tapo import TapoController
from utils.logger import setup_logging
from charging_state_handler import ChargingStateHandler
from services.boiler_scheduler import BoilerScheduler, BoilerConfig
from services.tapo import TapoService
from services.runtime_status import runtime_status_store
from logs.webapp.server import run_web_server

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
    _start_web_server()

    logging.info("Starting Bluetti DC cycle test...")

    boiler_task = None

    def handle_stop_signal(signum, frame):
        logging.info("Stop signal received, performing cleanup...")
        if boiler_task:
            boiler_task.cancel()
        bluetti_controller.stop()
        logging.info("Cleanup complete, exiting.")
        exit(0)

    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_stop_signal)
    signal.signal(signal.SIGINT, handle_stop_signal)

    # Optional one-shot DC test; disable via env RUN_DC_TEST=false
    # Default off so the state machine starts immediately; enable if you need the DC pulse.
    run_dc_test = os.getenv("RUN_DC_TEST", "false").lower() in ["1", "true", "yes", "on"]
    if run_dc_test:
        await test_bluetti_dc_cycle(bluetti_controller)

    # Optional boiler scheduler (runs concurrently with charging logic)
    boiler_config = BoilerConfig.from_env()
    if boiler_config.enabled:
        boiler_tapo = TapoService(
            username=boiler_config.username,
            password=boiler_config.password,
            ip_address=boiler_config.ip_address,
        )
        boiler_scheduler = BoilerScheduler(boiler_tapo, config=boiler_config)
        boiler_task = asyncio.create_task(boiler_scheduler.run())
        logging.info("Boiler scheduler started in background.")
    else:
        logging.info("Boiler scheduler disabled.")

    # Main charging state machine
    charging_handler = ChargingStateHandler(tapo_controller, bluetti_controller)
    while True:
        await charging_handler.handle_state()


def _start_web_server():
    web_enabled = os.getenv("WEBAPP_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    if not web_enabled:
        logging.info("Webapp server disabled by WEBAPP_ENABLED.")
        return

    window_min = int(os.getenv("CONNECTION_WINDOW_MIN", "5"))
    runtime_status_store.set_connection_meta("window_min", window_min)

    web_port = int(os.getenv("WEBAPP_PORT", "8080"))
    thread = threading.Thread(target=run_web_server, kwargs={"host": "0.0.0.0", "port": web_port}, daemon=True)
    thread.start()
    logging.info("Webapp server started on port %s", web_port)


load_dotenv()

asyncio.run(main(TapoController(), BluettiController()))
