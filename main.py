import asyncio
from dotenv import load_dotenv
from fingerbotController import FingerBotController
from tapoController import TapoController


async def main():
    load_dotenv()

    fingerbotController = FingerBotController()
    await fingerbotController.press_button()

    tapoController = TapoController()
    await tapoController.initialize()

    await tapoController.turn_on()
    await asyncio.sleep(2)  # Simulate some delay
    await tapoController.turn_off()


asyncio.run(main())
