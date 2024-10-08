import asyncio
from dotenv import load_dotenv
from fingerbotController import FingerBotController
from tapoController import TapoController
from bluettiController import BluettiController


async def main():
    load_dotenv()
    # statuses
    t110_online = False
    t110_charging = False   


#    fingerbotController = FingerBotController()
#    await fingerbotController.press_button()

    tapoController = TapoController()
    await tapoController.initialize()
#    t110_online = await tapoController.get_is_online()
#    print('online' if t110_online else 'offline')
#
#    if t110_online:
#        t110_charging = await tapoController.get_is_charging()

    status = await tapoController.get_status()
    if status:
        t110_online = status["is_online"]
        t110_charging = status["is_charging"]

    print(f"Is online: {t110_online}")
    print(f"Is charging: {t110_charging}")

    #await tapoController.turn_on()
    #await asyncio.sleep(2)  # Simulate some delay
    #await tapoController.turn_off()

#    bluetiiController = BluettiController()
#    await bluetiiController.initialize()
#    await asyncio.sleep(2)
#    bluetiiController.turn_dc()

#    # Keep the service running
#    while True:
#        pass



asyncio.run(main())
