import logging
from services.tapo import TapoService
from models.tapo import TapoStatus


class TapoController:
    def __init__(self):
        self.tapo = TapoService()
        self.status = TapoStatus()

    async def initialize(self):
        try:
            await self.tapo.initialize()
            self.status.set_online(True)
        except Exception:
            logging.debug("TAPO: Failed to initialize")
            self.status.set_online(False)

    async def get_status(self):
        try:
            await self.tapo.initialize()
            self.status.set_online(True)
            device_info = await self.tapo.get_state()
            self.status.set_charging(device_info.device_on)
        except Exception:
            self.status.reset()
            # Force a fresh login next time after auth/network failures
            self.tapo.initialized = False
            self.tapo.device = None
            logging.debug("TAPO: Failed to get status")

    async def start_charging(self):
        await self.tapo.initialize()
        await self.tapo.turn_on()
        await self.tapo.get_state()

    async def stop_charging(self):
        await self.tapo.initialize()
        await self.tapo.turn_off()
        await self.tapo.get_state()

    async def get_current_power(self):
        """Fetch the current power draw from the TAPO device."""
        try:
            await self.tapo.initialize()
            power = await self.tapo.get_current_power()
            logging.info(f"TAPO: Current power usage: {power}W")
            return power
        except Exception:
            # Reset session so we re-login after a 403/offline event
            self.tapo.initialized = False
            self.tapo.device = None
            logging.debug("TAPO: Failed to get current power")
            raise
