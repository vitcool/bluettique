import os
import asyncio
import logging
from tapo import ApiClient


class TapoService:
    def __init__(self, username: str | None = None, password: str | None = None, ip_address: str | None = None):
        # Allow per-device credentials while keeping defaults for the charging plug.
        self.tapo_username = username or os.getenv("TAPO_USERNAME")
        self.tapo_password = password or os.getenv("TAPO_PASSWORD")
        # Prefer a dedicated charging socket identifier if provided (e.g., IP)
        self.ip_address = ip_address or os.getenv("CHARGING_SOCKET_DEVICE_ID") or os.getenv("TAPO_IP_ADDRESS")
        self.device = None
        # Skip re-login when we already have a paired device
        self.initialized = False

    async def initialize(self):
        # Always clear session and re-login to avoid stale/expired sessions.
        self.initialized = False
        self.device = None
        logging.info("TAPO: Reconnecting to device %s", self.ip_address)
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
        try:
            await self.device.on()
        except Exception:
            # Session may be stale; reset and retry once
            self.initialized = False
            self.device = None
            logging.debug("TAPO: turn_on failed; resetting session and retrying")
            await self.initialize()
            await self.device.on()

    async def turn_off(self):
        logging.info("TAPO: Turning device off...")
        try:
            await self.device.off()
        except Exception:
            self.initialized = False
            self.device = None
            logging.debug("TAPO: turn_off failed; resetting session and retrying")
            await self.initialize()
            await self.device.off()

    async def get_state(self):
        try:
            return await self.device.get_device_info()
        except Exception:
            # Force re-login on next attempt after auth/network failures
            self.initialized = False
            self.device = None
            logging.debug("TAPO: Failed to get state; session will be reset")
            raise

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
