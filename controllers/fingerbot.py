import os
from services.fingerbot import FingerBotService


class FingerBotController:
    def __init__(self):
        fingerbot_local_key = os.getenv("FINGERBOT_LOCAL_KEY_MAIN")
        fingerbot_mac = os.getenv("FINGERBOT_MAC_MAIN")
        fingerbot_uuid = os.getenv("FINGERBOT_UUID_MAIN")
        fingerbot_dev_id = os.getenv("FINGERBOT_DEV_ID_MAIN")

        self.fingerbot = FingerBotService(
            fingerbot_mac, fingerbot_local_key, fingerbot_uuid, fingerbot_dev_id
        )
        
        # add the second device here

    async def press_button(self):
        connected = False
        self.fingerbot.pairing_complete = False
        while not connected:
            try:
                connected = await self.fingerbot.connect()
            except Exception:
                print("FINGERBOT: Connection failed, retrying...")

        print("FINGERBOT: Connected")
        self.fingerbot.press_button()
        print("FINGERBOT: Button pressed")
        self.fingerbot.disconnect()
        print("FINGERBOT: Disconnected")
