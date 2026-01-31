import asyncio
import logging
from services.bluettiMqtt import BluettiMQTTService

CONNECTION_RETRY_ATTEMPTS = 5


class BluettiController:
    def __init__(self):
        self.bluetti = BluettiMQTTService()
        self.turned_on = False
        self.connection_set = False
        self.ac_turned_on = False
        self.dc_turned_on = False

    async def initialize(self):
        if self.connection_set:
            logging.info("BluettiController already connected; skipping initialize.")
            return

        logging.info("BluettiController initializing.")
        for attempt in range(CONNECTION_RETRY_ATTEMPTS):
            if await self.bluetti.connect():
                logging.info("BluettiMQTTService connected.")
                self.connection_set = True
                self.turned_on = True
                return
            logging.info(
                f"Retrying connection to BluettiMQTTService... (Attempt {attempt + 1})"
            )
            await asyncio.sleep(10)
        logging.info(
            f"Failed to connect to BluettiMQTTService after {CONNECTION_RETRY_ATTEMPTS} attempts."
        )
        self.connection_set = False
        self.turned_on = False

    def turn_dc(self, state: str):
        logging.info(f"Bluetti: Turning DC device {state}")
        self.dc_turned_on = state == "ON"
        self.bluetti.set_dc_output(state)

    def turn_ac(self, state: str):
        logging.info(f"Bluetti: Turning AC device {state}")
        self.ac_turned_on = state == "ON"
        self.bluetti.set_ac_output(state)

    def power_off(self):
        logging.info("Bluetti: Turning off device")
        # self.bluetti.power_off() sometimes it works, sometimes it doesn't
        self.stop()
        # self.bluetti.reset_status()
        self.turned_on = False
        self.connection_set = False
        self.bluetti.status.reset_output_status()

    def get_status(self):
        status = self.bluetti.status.get_status()
        self.ac_turned_on = status["ac_output_on"]
        self.dc_turned_on = status["dc_output_on"]
        return status

    def stop(self):
        logging.info("Bluetti: Stopping MQTT client and broker")
        self.bluetti.stop_client()
        self.bluetti.stop_broker()
        self.bluetti.disconnect_device()
