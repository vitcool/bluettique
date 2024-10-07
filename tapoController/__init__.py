import os
import asyncio
from tapo import ApiClient

class Tapo():
    def __init__(self):
        self.tapo_username = os.getenv("TAPO_USERNAME")
        self.tapo_password = os.getenv("TAPO_PASSWORD")
        self.ip_address = os.getenv("TAPO_IP_ADDRESS")
        self.device = None

    async def initialize(self):
        try:
            await asyncio.wait_for(self._login(), timeout=10)
            print("Pairing successful")
        except Exception:
            print("Pairing failed")
            raise
        

    async def _login(self):
        try:
            client = ApiClient(self.tapo_username, self.tapo_password)
            self.device = await client.p110(self.ip_address)
        except Exception:
            raise

    async def turn_on(self):
        print("TAPO:Turning device on...")
        await self.device.on()

    async def turn_off(self):
        print("TAPO: Turning device off...")
        await self.device.off()

    async def get_state(self):
        device_info = await self.device.get_device_info()
        print(f"TAPO: Device info: {device_info.to_dict()}")

class TapoController():
    def __init__(self):
        self.tapo = Tapo()
        self.online = False

    async def initialize(self):
        try:
            await self.tapo.initialize()
            print("TAPO online")
            return True
        except Exception:
            print("TAPO offline")
            return False
            

    async def turn_on(self):
#        await self.tapo._login()
        await self.tapo.turn_on()
        await self.tapo.get_state()

    async def turn_off(self):
#        await self.tapo._login()
        await self.tapo.turn_off()
        await self.tapo.get_state()
    
