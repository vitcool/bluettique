import asyncio
import logging
import time
from services.bluettiMqtt import BluettiMQTTService

CONNECTION_RETRY_ATTEMPTS = 5


class BluettiController:
    def __init__(self):
        self.bluetti = BluettiMQTTService()
        self.connection_set = False

    async def initialize(self):
        if self.connection_set:
            if self.bluetti.device_connected:
                logging.info("BluettiController already connected; skipping initialize.")
                return
            logging.info(
                "BluettiController flagged connected but device is not; attempting reconnection."
            )
            self.connection_set = False

        logging.info("BluettiController initializing.")
        for attempt in range(CONNECTION_RETRY_ATTEMPTS):
            if await self.bluetti.connect():
                logging.info("BluettiMQTTService connected.")
                self.connection_set = True
                return
            logging.info(
                f"Retrying connection to BluettiMQTTService... (Attempt {attempt + 1})"
            )
            await asyncio.sleep(10)
        logging.info(
            f"Failed to connect to BluettiMQTTService after {CONNECTION_RETRY_ATTEMPTS} attempts."
        )
        self.connection_set = False

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
        self.bluetti.stop_client()
        self.bluetti.stop_broker()
        self.bluetti.disconnect_device()
        self.connection_set = False
