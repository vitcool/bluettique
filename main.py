import asyncio
import signal
from dotenv import load_dotenv
from fingerbotController import FingerBotController
from tapoController import TapoController
from bluettiController import BluettiController


async def main():
    load_dotenv()
    # statuses
    t110_online = False
    t110_charging = False
    tapo_initial_sucess = False
    bluetti_initial_success = False

#    fingerbotController = FingerBotController()
#    await fingerbotController.press_button()

    tapoController = TapoController()
#    bluetiiController = BluettiController()
    
    tapo_initial_sucess = await tapoController.initialize()   

    def handle_interrupt(signal, frame):
        print("KeyboardInterrupt received, stopping services...")
#        bluetiiController.stop()
        exit(0)

    # Register the signal handler for KeyboardInterrupt
    signal.signal(signal.SIGINT, handle_interrupt)

#    bluetti_initial_success = await bluetiiController.initialize()

    if not tapo_initial_sucess:
        print("Failed to initialize Tapo controller")
        return

    if not bluetti_initial_success:
        print("Failed to initialize Bluetooth controller")
        return
    
    while True:
        tapo_status = await tapoController.get_status()
        if tapo_status:
            t110_online = tapo_status["is_online"]
            t110_charging = tapo_status["is_charging"]
            
        print(f"TAPO: Is online: {t110_online}")
        print(f"TAPO: Is charging: {t110_charging}")
        
#        bluetti_status = await bluetiiController.get_status()
        if bluetti_status:
            bluetti_total_battery_percent = bluetti_status["total_battery_percent"]
            bluetti_ac_output_on = bluetti_status["ac_output_on"]
            bluetti_dc_output_on = bluetti_status["dc_output_on"]
            
        print(f"BLUETTI: Total battery percent: {bluetti_total_battery_percent}")
        print(f"BLUETTI: AC output on: {bluetti_ac_output_on}")
        print(f"BLUETTI: DC output on: {bluetti_dc_output_on}")

        await asyncio.sleep(5)  

    #await tapoController.turn_on()
    #await asyncio.sleep(2)  # Simulate some delay
    #await tapoController.turn_off()

#    await asyncio.sleep(2)
#    bluetiiController.turn_dc()

#    # Keep the service running
#    while True:
#        pass



asyncio.run(main())
