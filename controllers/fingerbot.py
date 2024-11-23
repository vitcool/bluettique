import os
import logging
from services.fingerbot import FingerBotService


class FingerBotController:
    def __init__(self):
        fingerbot_local_key_main = os.getenv("FINGERBOT_LOCAL_KEY_MAIN")
        fingerbot_mac_main = os.getenv("FINGERBOT_MAC_MAIN")
        fingerbot_uuid_main = os.getenv("FINGERBOT_UUID_MAIN")
        fingerbot_dev_id_main = os.getenv("FINGERBOT_DEV_ID_MAIN")
        
        fingerbot_local_key_additional = os.getenv("FINGERBOT_LOCAL_KEY_ADD")
        fingerbot_mac_additional = os.getenv("FINGERBOT_MAC_ADD")
        fingerbot_uuid_additional = os.getenv("FINGERBOT_UUID_ADD")
        fingerbot_dev_id_additional = os.getenv("FINGERBOT_DEV_ID_ADD")

        self.fingerbot_main = FingerBotService(
            fingerbot_mac_main, fingerbot_local_key_main, fingerbot_uuid_main, fingerbot_dev_id_main
        )
        
        self.with_additional = fingerbot_local_key_additional is not None
        
        if (self.with_additional):
            self.fingerbot_additional = FingerBotService(
                fingerbot_mac_additional, fingerbot_local_key_additional, fingerbot_uuid_additional, fingerbot_dev_id_additional
            )
        
    async def press_button_for_device(self, fingerbot_service, device_name):
        connected = False
        fingerbot_service.pairing_complete = False
        
        while not connected:
            try:
                connected = await fingerbot_service.connect()
            except Exception as e:
                logging.debug(f"{device_name}: Connection failed, retrying... Exception: {e}")

        logging.debug(f"{device_name}: Connected")
        fingerbot_service.press_button()
        logging.info(f"{device_name}: Button pressed")
        fingerbot_service.disconnect()
        logging.debug(f"{device_name}: Disconnected")

    async def press_button(self, press_additional=True):
        await self.press_button_for_device(self.fingerbot_main, "FINGERBOT_MAIN")
        
        if press_additional and self.with_additional:
            await self.press_button_for_device(self.fingerbot_additional, "FINGERBOT_ADDITIONAL")
