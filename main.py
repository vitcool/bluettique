import asyncio
from dotenv import load_dotenv
from fingerbotController import FingerBotController


async def main():
    load_dotenv()

    fingerbotController = FingerBotController()
    await fingerbotController.press_button()

asyncio.run(main())
