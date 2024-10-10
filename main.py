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

    # fingerbotController = FingerBotController()
    # await fingerbotController.press_button()

    tapoController = TapoController()
    bluetiiController = BluettiController()
    
    tapo_initial_sucess = await tapoController.initialize()   
    await bluetiiController.initialize()

    if not tapo_initial_sucess:
        print("Failed to initialize Tapo controller")
        return
    
    while True:
        tapoStatus = await tapoController.get_status()
        if tapoStatus:
            t110_online = tapoStatus["is_online"]
            t110_charging = tapoStatus["is_charging"]
            
        print(f"Is online: {t110_online}")
        print(f"Is charging: {t110_charging}")
        
        bluettiStatus = await bluetiiController.get_status()
        if bluettiStatus:
            bluetti_total_battery_percent = bluettiStatus["total_battery_percent"]
            bluetti_ac_output_on = bluettiStatus["ac_output_on"]
            bluetti_dc_output_on = bluettiStatus["dc_output_on"]
            
        print(f"Total battery percent: {bluetti_total_battery_percent}")
        print(f"AC output on: {bluetti_ac_output_on}")
        print(f"DC output on: {bluetti_dc_output_on}")

        await asyncio.sleep(60)  # Wait for 1 minute before checking again

    #await tapoController.turn_on()
    #await asyncio.sleep(2)  # Simulate some delay
    #await tapoController.turn_off()

#    await asyncio.sleep(2)
#    bluetiiController.turn_dc()

#    # Keep the service running
#    while True:
#        pass



asyncio.run(main())
