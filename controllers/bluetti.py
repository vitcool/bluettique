import asyncio
import logging
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

    def get_status(self):
        return self.bluetti.status.get_status()

    def stop(self):
        logging.info("Bluetti: Stopping MQTT client and broker")
        self.bluetti.stop_client()
        self.bluetti.stop_broker()
        self.bluetti.disconnect_device()
        self.connection_set = False
