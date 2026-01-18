import os
import asyncio
import logging
from tapo import ApiClient


class TapoService:
    def __init__(self):
        self.tapo_username = os.getenv("TAPO_USERNAME")
        self.tapo_password = os.getenv("TAPO_PASSWORD")
        self.ip_address = os.getenv("TAPO_IP_ADDRESS")
        self.device = None

    async def initialize(self):
        try:
            await asyncio.wait_for(self._login(), timeout=20)
            logging.info("TAPO: Pairing successful")
        except Exception:
            logging.info("TAPO: Pairing failed")
            raise

    async def _login(self):
        try:
            client = ApiClient(self.tapo_username, self.tapo_password)
            self.device = await client.p110(self.ip_address)
        except Exception as e:
            logging.debug(f"TAPO: Login failed with error: {e}")
            raise

    async def turn_on(self):
        logging.info("TAPO: Turning device on...")
        await self.device.on()

    async def turn_off(self):
        logging.info("TAPO: Turning device off...")
        await self.device.off()

    async def get_state(self):
        return await self.device.get_device_info()

    async def get_current_power(self):
        logging.info("TAPO: Fetching current power usage...")
        return await self.device.get_current_power()
