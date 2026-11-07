import asyncio
import signal
import logging
import threading
from dotenv import load_dotenv
from controllers.bluetti import BluettiController
from controllers.tapo import TapoController
from utils.env import bool_env, int_env
from utils.logger import setup_logging
from charging_state_handler import ChargingStateHandler
from services.boiler_scheduler import BoilerScheduler, BoilerConfig
from services.tapo import TapoService
from services.runtime_status import runtime_status_store
from services.user_settings import user_settings
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
    _start_web_server(bluetti_controller)

    boiler_task = asyncio.create_task(
        manage_boiler_scheduler(BoilerConfig.from_env()),
        name="boiler-scheduler-manager",
    )
    bluetti_watchdog_task = asyncio.create_task(
        bluetti_controller.monitor_connection(
            lambda: user_settings.bluetti_monitoring_enabled
        ),
        name="bluetti-connection-watchdog",
    )

    def handle_stop_signal(signum, frame):
        logging.info("Stop signal received, performing cleanup...")
        if boiler_task:
            boiler_task.cancel()
        if bluetti_watchdog_task:
            bluetti_watchdog_task.cancel()
        bluetti_controller.stop()
        logging.info("Cleanup complete, exiting.")
        exit(0)

    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_stop_signal)
    signal.signal(signal.SIGINT, handle_stop_signal)

    # Optional one-shot DC test; disable via env RUN_DC_TEST=false
    # Default off so the state machine starts immediately; enable if you need the DC pulse.
    run_dc_test = bool_env("RUN_DC_TEST", False)
    if run_dc_test:
        logging.info("Starting Bluetti DC cycle test...")
        await test_bluetti_dc_cycle(bluetti_controller)

    # Main charging state machine
    charging_handler = ChargingStateHandler(tapo_controller, bluetti_controller)
    while True:
        await charging_handler.handle_state()


async def manage_boiler_scheduler(config: BoilerConfig):
    """Start and stop the boiler scheduler when its persisted dashboard toggle changes."""
    scheduler = None
    scheduler_task = None
    previously_enabled = False
    try:
        while True:
            enabled = user_settings.boiler_enabled
            if enabled and (scheduler_task is None or scheduler_task.done()):
                if scheduler is None:
                    boiler_tapo = TapoService(
                        username=config.username,
                        password=config.password,
                        ip_address=config.ip_address,
                    )
                    scheduler = BoilerScheduler(boiler_tapo, config=config)
                config.enabled = True
                scheduler_task = asyncio.create_task(
                    scheduler.run(), name="boiler-scheduler"
                )
                logging.info("Boiler scheduler started from dashboard setting.")
            elif not enabled and previously_enabled:
                if scheduler_task is not None and not scheduler_task.done():
                    scheduler_task.cancel()
                    await asyncio.gather(scheduler_task, return_exceptions=True)
                scheduler_task = None
                config.enabled = False
                if scheduler is not None:
                    await scheduler.disable()
                logging.info("Boiler scheduler stopped from dashboard setting.")
            previously_enabled = enabled
            await asyncio.sleep(1)
    finally:
        if scheduler_task is not None and not scheduler_task.done():
            scheduler_task.cancel()
            await asyncio.gather(scheduler_task, return_exceptions=True)
        if scheduler is not None:
            await scheduler.disable()


def _start_web_server(bluetti_controller):
    web_enabled = bool_env("WEBAPP_ENABLED", True)
    if not web_enabled:
        logging.info("Webapp server disabled by WEBAPP_ENABLED.")
        return

    window_min = int_env("CONNECTION_WINDOW_MIN", 5)
    runtime_status_store.set_connection_meta("window_min", window_min)
    runtime_status_store.set_connection_meta(
        "status_refresh_ms",
        int_env("WEBAPP_STATUS_REFRESH_MS", 2000, min_value=250, max_value=60000),
    )
    runtime_status_store.set_connection_meta(
        "logs_refresh_ms",
        int_env("WEBAPP_LOGS_REFRESH_MS", 2000, min_value=250, max_value=60000),
    )

    web_port = int_env("WEBAPP_PORT", 8080)
    loop = asyncio.get_running_loop()
    from logs.webapp.server import set_power_off_scheduler

    set_power_off_scheduler(
        lambda: asyncio.run_coroutine_threadsafe(
            bluetti_controller.power_off_until_confirmed(
                int_env("POWER_OFF_MAX_ATTEMPTS", 5, min_value=1),
                int_env("POWER_OFF_QUIET_SEC", 60, min_value=1),
            ),
            loop,
        )
    )
    thread = threading.Thread(target=run_web_server, kwargs={"host": "0.0.0.0", "port": web_port}, daemon=True)
    thread.start()
    logging.info("Webapp server started on port %s", web_port)


load_dotenv()

asyncio.run(main(TapoController(), BluettiController()))
