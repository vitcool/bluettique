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
            print("TAPO: Failed to initialize")
            self.status.set_online(False)

    async def get_status(self):
        try:
            await self.tapo.initialize()
            self.status.set_online(True)
            device_info = await self.tapo.get_state()
            self.status.set_charging(device_info.device_on)
        except Exception:
            self.status.reset()
            print("TAPO: Failed to get status")

    async def start_charging(self):
        await self.tapo.turn_on()
        await self.tapo.get_state()

    async def stop_charging(self):
        await self.tapo.turn_off()
        await self.tapo.get_state()
