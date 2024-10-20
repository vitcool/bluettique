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

    tapoController = TapoController()
    bluettiController = BluettiController()
    fingerbotController = FingerBotController()
            
    tapo_initial_sucess = await tapoController.initialize()   

    def handle_interrupt(signal, frame):
        print("KeyboardInterrupt received, stopping services...")
        bluettiController.stop()
        exit(0)

    # Register the signal handler for KeyboardInterrupt
    signal.signal(signal.SIGINT, handle_interrupt)

    if not tapo_initial_sucess:
        print("Failed to initialize Tapo controller")

    while not await bluettiController.initialize():
        print("Failed to initialize Bluetooth controller")
        await fingerbotController.press_button()

    cycle_counter = 0
    while True:            
        cycle_counter += 1
        print(f"CYCLE #{cycle_counter} START")
        should_turn_on_bluetti = False
        
        # in case if bluetti is turned on manually
        if not bluettiController.turned_on:
            print("Bluetti is turned off")
            await bluettiController.initialize()
        
        if not tapo_initial_sucess:
            tapo_initial_sucess = await tapoController.initialize()
            if not tapo_initial_sucess:
                print("Failed to initialize Tapo controller")
        
        tapo_status = await tapoController.get_status()
        if tapo_status:
            if t110_online == True and tapo_status["is_online"] == False:
                print("TAPO: Device went offline")
                should_turn_on_bluetti = True
                
            t110_online = tapo_status["is_online"]
            t110_charging = tapo_status["is_charging"]
            
        print(f"TAPO: Is online: {t110_online}")
        print(f"TAPO: Is charging: {t110_charging}")
        
        bluetti_status = await bluettiController.get_status()

        if bluetti_status:
            bluetti_total_battery_percent = bluetti_status["total_battery_percent"]
            bluetti_ac_output_on = bluetti_status["ac_output_on"]
            bluetti_dc_output_on = bluetti_status["dc_output_on"]
            bluetti_ac_output_power = bluetti_status["ac_output_power"]
            bluetti_dc_output_power = bluetti_status["dc_output_power"]
            bluetti_ac_input_power = bluetti_status["ac_input_power"]
            bluetti_dc_input_power = bluetti_status.get("dc_input_power", 0)
        
        if bluetti_total_battery_percent is not None:
            should_turn_off_bluetti = not(bluetti_ac_output_on or bluetti_dc_output_on)
            # debug print
            print(f"BLUETTI: Total battery percent: {bluetti_total_battery_percent}")
            print(f"BLUETTI: AC output on: {bluetti_ac_output_on}")
            print(f"BLUETTI: DC output on: {bluetti_dc_output_on}")
            print(f"BLUETTI: AC output power: {bluetti_ac_output_power}")
            print(f"BLUETTI: DC output power: {bluetti_dc_output_power}")
            print(f"BLUETTI: AC input: {bluetti_ac_input_power}")
            print(f"BLUETTI: DC input: {bluetti_dc_input_power}")
            
            bluetti_is_charging = bluetti_ac_input_power > 0 or bluetti_dc_input_power > 0

            # turn on charger if bluetti is not charging and battery is not full
            if t110_online and not bluetti_is_charging and not t110_charging:
                if bluetti_total_battery_percent < 100:
                    print("Turning on charger")
                    should_turn_off_bluetti = False
                    await tapoController.turn_on()
                if bluettiController.ac_turned_on:
                    print("Turning off AC output")
                    bluettiController.turn_ac("OFF")

            # turn off charger if bluetti is charging and battery is full
            if t110_online and t110_charging and bluetti_total_battery_percent == 100:
                print("Turning off charger")
                await tapoController.turn_off()
                if bluetti_ac_output_power == 0:
                    print("Turning off AC output - no consumption")
                    bluettiController.turn_ac("OFF")
                    bluettiController.turn_dc("OFF")
                    should_turn_off_bluetti = True

            # turn AC on if t110 is offline and turn AC off if no consumption 
            if (bluettiController.turned_on or should_turn_on_bluetti) and not bluetti_ac_output_on and (not t110_online or not tapo_initial_sucess):
                if not bluettiController.turned_on:
                    print("Turning on Bluetti")
                    await fingerbotController.press_button()        
                    await bluettiController.initialize()
                
                print("Turning on AC output")
                bluettiController.turn_ac("ON")
                await asyncio.sleep(2)
                print("Turning on DC output")
                bluettiController.turn_dc("ON")
                should_turn_off_bluetti = False
                
                await asyncio.sleep(70) # wait till consumption is stable and messages from Bluetti are received

                bluetti_status = await bluettiController.get_status()
                if bluetti_status:
                    bluetti_ac_output_power = bluetti_status["ac_output_power"]
                    bluetti_dc_output_power = bluetti_status["dc_output_power"]
                # if bluetti_ac_output_power == 0 - dc below is added for testing
                if bluetti_ac_output_power == 0 and bluetti_dc_output_power == 0:
                    print("Turning Bluetti off - no consumption")
                    bluettiController.turn_ac("OFF")
                    bluettiController.turn_dc("OFF") # DC just for testing
                    should_turn_off_bluetti = True
            
            if bluettiController.turned_on and should_turn_off_bluetti and not bluetti_is_charging:
                print("Turning off Bluetti")
                bluettiController.power_off()
                await fingerbotController.press_button()
        else:
            print("Waiting to get bluetti status")
            
        print(f"CYCLE #{cycle_counter} FINISH")
        await asyncio.sleep(30)  

asyncio.run(main())
