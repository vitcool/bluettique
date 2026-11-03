import asyncio
import logging
import time
from services.bluettiMqtt import BluettiMQTTService
from utils.env import int_env

class BluettiController:
    def __init__(self):
        self.bluetti = BluettiMQTTService()
        self.connection_set = False
        self._watchdog_enabled = False
        self.connection_retry_attempts = int_env(
            "BLUETTI_CONNECTION_RETRY_ATTEMPTS", 2, min_value=1
        )
        self.telemetry_stale_sec = int_env("CONNECTION_WINDOW_MIN", 5, min_value=1) * 60
        self.watchdog_interval_sec = int_env(
            "BLUETTI_WATCHDOG_INTERVAL_SEC", 15, min_value=1
        )
        self._initialize_lock = asyncio.Lock()

    async def initialize(self):
        async with self._initialize_lock:
            await self._initialize_locked()

    async def _initialize_locked(self):
        if self.connection_set:
            battery_updated_at = self.bluetti.status.battery_updated_at
            telemetry_fresh = (
                battery_updated_at is not None
                and time.monotonic() - battery_updated_at <= self.telemetry_stale_sec
            )
            broker_running = self.bluetti.is_broker_running()
            if self.bluetti.device_connected and telemetry_fresh and broker_running:
                logging.info("BluettiController already connected; skipping initialize.")
                return
            if self.bluetti.device_connected or not broker_running:
                logging.warning(
                    "Bluetti connection is unhealthy (broker_running=%s, device_connected=%s, "
                    "telemetry_fresh=%s); resetting and reconnecting.",
                    broker_running,
                    self.bluetti.device_connected,
                    telemetry_fresh,
                )
                self.bluetti.reset_connection()
            else:
                logging.info(
                    "BluettiController flagged connected but device is not; attempting reconnection."
                )
            self.connection_set = False

        logging.info("BluettiController initializing.")
        for attempt in range(1, self.connection_retry_attempts + 1):
            if await self.bluetti.connect():
                logging.info("BluettiMQTTService connected.")
                self.connection_set = True
                self._watchdog_enabled = True
                return
            if attempt < self.connection_retry_attempts:
                logging.info(
                    "Retrying connection to BluettiMQTTService... (Attempt %s)",
                    attempt + 1,
                )
                await asyncio.sleep(10)

        logging.warning(
            "Bluetti pairing failed after %s controller attempts; resetting the Bluetooth adapter.",
            self.connection_retry_attempts,
        )
        await self.bluetti.reset_bluetooth_adapter()
        logging.info("Retrying Bluetti pairing after the Bluetooth adapter reset.")
        if await self.bluetti.connect():
            logging.info("BluettiMQTTService connected after Bluetooth adapter reset.")
            self.connection_set = True
            self._watchdog_enabled = True
            return

        logging.error(
            "Failed to connect to BluettiMQTTService after retries and adapter reset; "
            "exiting so Docker can restart the container.",
        )
        self.connection_set = False
        # docker-compose.yaml uses restart: unless-stopped. Let the failure
        # escape callers that handle ordinary connection errors so the process
        # exits and Docker can restart the container.
        raise SystemExit(1)

    async def monitor_connection(self):
        """Recover the broker/BLE link if it dies after the initial connection."""
        while True:
            await asyncio.sleep(self.watchdog_interval_sec)
            if not self._watchdog_enabled:
                continue

            battery_updated_at = self.bluetti.status.battery_updated_at
            telemetry_fresh = (
                battery_updated_at is not None
                and time.monotonic() - battery_updated_at <= self.telemetry_stale_sec
            )
            broker_running = self.bluetti.is_broker_running()
            if self.bluetti.device_connected and telemetry_fresh and broker_running:
                continue

            logging.warning(
                "Bluetti watchdog detected lost connection (broker_running=%s, "
                "device_connected=%s, telemetry_fresh=%s); reconnecting.",
                broker_running,
                self.bluetti.device_connected,
                telemetry_fresh,
            )
            try:
                await self.initialize()
            except SystemExit:
                # Keep the app alive and retry on the next watchdog pass. The
                # initialize path has already exhausted pairing and adapter reset.
                logging.error("Bluetti watchdog reconnect failed; will retry.")

    def turn_dc(self, state: str):
        logging.info(f"Bluetti: Turning DC device {state}")
        self.bluetti.set_dc_output(state)

    def turn_ac(self, state: str):
        logging.info(f"Bluetti: Turning AC device {state}")
        self.bluetti.set_ac_output(state)

    def power_off(self):
        logging.info("Bluetti: Turning off device")
        # self.bluetti.power_off() sometimes it works, sometimes it doesn't
        self.stop()
        # self.bluetti.reset_status()
        self.connection_set = False
        self._watchdog_enabled = False
        self.bluetti.status.reset_output_status()

    async def power_off_until_confirmed(self, max_attempts: int, quiet_sec: float) -> bool:
        """Send the power-off command until telemetry has been silent for quiet_sec; True once confirmed."""
        poll_sec = min(5.0, quiet_sec)
        for attempt in range(1, max_attempts + 1):
            await self.initialize()
            logging.info(f"Bluetti: Power off command (attempt {attempt}/{max_attempts})")
            self.bluetti.power_off()
            deadline = time.monotonic() + quiet_sec * 2
            while time.monotonic() < deadline:
                await asyncio.sleep(poll_sec)
                updated_at = self.bluetti.status.battery_updated_at
                if updated_at is None or time.monotonic() - updated_at >= quiet_sec:
                    logging.info("Bluetti: Power off confirmed (no telemetry for %.0fs)", quiet_sec)
                    self.power_off()
                    return True
            logging.warning(f"Bluetti: Still sending telemetry after power off (attempt {attempt}/{max_attempts})")
        return False

    def get_status(self):
        return self.bluetti.status.get_status()

    def stop(self):
        logging.info("Bluetti: Stopping MQTT client and broker")
        self._watchdog_enabled = False
        self.bluetti.stop_client()
        self.bluetti.stop_broker()
        self.bluetti.disconnect_device()
        self.connection_set = False
