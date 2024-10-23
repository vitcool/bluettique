import os
import asyncio
from tapo import ApiClient


class Tapo:
    def __init__(self):
        self.tapo_username = os.getenv("TAPO_USERNAME")
        self.tapo_password = os.getenv("TAPO_PASSWORD")
        self.ip_address = os.getenv("TAPO_IP_ADDRESS")
        self.device = None

    async def initialize(self):
        try:
            await asyncio.wait_for(self._login(), timeout=20)
            print("TAPO: Pairing successful")
        except Exception:
            print("TAPO: Pairing failed")
            raise

    async def _login(self):
        try:
            client = ApiClient(self.tapo_username, self.tapo_password)
            self.device = await client.p110(self.ip_address)
        except Exception as e:
            print(f"TAPO: Login failed with error: {e}")
            raise

    async def turn_on(self):
        print("TAPO: Turning device on...")
        await self.device.on()

    async def turn_off(self):
        print("TAPO: Turning device off...")
        await self.device.off()

    async def get_state(self):
        return await self.device.get_device_info()


class TapoStatus:
    def __init__(self, online=False, charging=False):
        self.online = online
        self.charging = charging

    def set_online(self, online: bool):
        """Set the online status and handle any additional logic."""
        self.online = online

    def set_charging(self, charging: bool):
        """Set the charging status and handle any additional logic."""
        self.charging = charging

    def reset(self):
        """Reset the status to its default values."""
        self.online = False
        self.charging = False
        print("Tapo status reset to default.")

    def get_status(self):
        """Get the current status as an object with properties 'online' and 'charging'."""
        return {"online": self.online, "charging": self.charging}


class TapoController:
    def __init__(self):
        self.tapo = Tapo()
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

    async def turn_on(self):
        await self.tapo.turn_on()
        await self.tapo.get_state()

    async def turn_off(self):
        await self.tapo.turn_off()
        await self.tapo.get_state()
