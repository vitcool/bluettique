import os
from services.fingerbot import FingerBotService


class FingerBotController:
    def __init__(self):
        fingerbot_local_key = os.getenv("FINGERBOT_LOCAL_KEY")
        fingerbot_mac = os.getenv("FINGERBOT_MAC")
        fingerbot_uuid = os.getenv("FINGERBOT_UUID")
        fingerbot_dev_id = os.getenv("FINGERBOT_DEV_ID")

        self.fingerbot = FingerBotService(
            fingerbot_mac, fingerbot_local_key, fingerbot_uuid, fingerbot_dev_id
        )

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
