import os
import asyncio
import logging
from tapo import ApiClient


class TapoService:
    def __init__(self):
        self.tapo_username = os.getenv("TAPO_USERNAME")
        self.tapo_password = os.getenv("TAPO_PASSWORD")
        # Prefer a dedicated charging socket identifier if provided (e.g., IP)
        self.ip_address = os.getenv("CHARGING_SOCKET_DEVICE_ID") or os.getenv("TAPO_IP_ADDRESS")
        self.device = None
        # Skip re-login when we already have a paired device
        self.initialized = False

    async def initialize(self):
        if self.device is not None and self.initialized:
            return
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
            self.initialized = True
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
        raw_power = await self.device.get_current_power()
        # The SDK returns a CurrentPowerResult object; unwrap to the numeric value.
        if raw_power is None:
            return None
        if isinstance(raw_power, (int, float)):
            return float(raw_power)
        if hasattr(raw_power, "current_power"):
            try:
                return float(raw_power.current_power)
            except (TypeError, ValueError):
                return None
        if isinstance(raw_power, dict) and "current_power" in raw_power:
            try:
                return float(raw_power["current_power"])
            except (TypeError, ValueError):
                return None
        try:
            return float(raw_power)
        except (TypeError, ValueError):
            return None
