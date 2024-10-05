import asyncio
from dotenv import load_dotenv
import os
from fingerbotController import FingerBot


async def main():
    load_dotenv()

    fingerbot_local_key = os.getenv("FINGERBOT_LOCAL_KEY")
    fingerbot_mac = os.getenv("FINGERBOT_MAC")
    fingerbot_uuid = os.getenv("FINGERBOT_UUID")
    fingerbot_dev_id = os.getenv("FINGERBOT_DEV_ID")

    fingerbot = FingerBot(
        fingerbot_mac, fingerbot_local_key, fingerbot_uuid, fingerbot_dev_id
    )

    await fingerbot.connect()
    
    fingerbot.press_button()

asyncio.run(main())
