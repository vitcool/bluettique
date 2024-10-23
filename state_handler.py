import asyncio
import os
from enum import Enum


class SystemState(Enum):
    INITIAL_CHECK = 0
    IDLE = 1
    LONG_IDLE = 2
    CHECK_STATUS = 3
    START_CHARGING = 4
    STOP_CHARGING = 5
    TURN_AC_ON = 6
    TURN_OFF = 7


async def handle_state(
    state: SystemState, tapoController, bluettiController, fingerbotController
) -> SystemState:
    print("Handle ", state, " state")

    if state == SystemState.INITIAL_CHECK:
        """May be repalced in the future if bluetti params are stored in a file"""
        print("Initial check started")

        if not bluettiController.connection_set:
            await fingerbotController.press_button()
            await bluettiController.initialize()

        while not bluettiController.get_status().get("info_received"):
            await asyncio.sleep(5)

        return SystemState.CHECK_STATUS

    elif state == SystemState.IDLE:
        await asyncio.sleep(int(os.getenv("IDLE_INTERVAL")))
        return SystemState.CHECK_STATUS
    
    elif state == SystemState.IDLE:
        await asyncio.sleep(3 * int(os.getenv("IDLE_INTERVAL")))
        return SystemState.CHECK_STATUS

    elif state == SystemState.CHECK_STATUS:
        await tapoController.get_status()
        tapo_status = tapoController.status.get_status()
        bluetti_status = bluettiController.get_status()
        is_tapo_online = tapo_status.get('online')
        is_tapo_charing = tapo_status.get('charging')

        total_battery_percent_bluetti = bluetti_status.get("total_battery_percent")
        ac_output_on_bluetti = bluetti_status.get("ac_output_on")
        dc_output_on_bluetti = bluetti_status.get("dc_output_on")
        ac_output_power_bluetti = bluetti_status.get("ac_output_power")
        dc_output_power_bluetti = bluetti_status.get("dc_output_power")
        
        if is_tapo_online and not is_tapo_charing and total_battery_percent_bluetti < 100:
            return SystemState.START_CHARGING
        
        if is_tapo_charing and total_battery_percent_bluetti == 100:
            return SystemState.STOP_CHARGING
        
        if not is_tapo_online:
            return SystemState.TURN_AC_ON
        
        if not ac_output_on_bluetti and not dc_output_on_bluetti and not is_tapo_charing:
            return SystemState.TURN_OFF
        
        return SystemState.IDLE
    
    elif state == SystemState.START_CHARGING:
        await tapoController.start_charging()
        # just for testing removing ac  - playing with dc only
        # if bluettiController.ac_turned_on:
        #     bluettiController.turn_ac("OFF")
        if bluettiController.dc_turned_on:
            bluettiController.turn_dc("OFF")
        
        return SystemState.IDLE
    
    elif state == SystemState.STOP_CHARGING:
        await tapoController.stop_charging()
        
        return SystemState.TURN_OFF
    
    elif state == SystemState.TURN_OFF:
        bluettiController.power_off()
        await fingerbotController.press_button()
        
        return SystemState.IDLE
    
    elif state == SystemState.TURN_AC_ON:
        if not bluettiController.turned_on:
            await fingerbotController.press_button()
            await bluettiController.initialize()
        
        if not bluettiController.ac_turned_on:
            #  just for testing commented out ac - playing with dc only
            # bluettiController.turn_ac("ON")
            # await asyncio.sleep(2)
            bluettiController.turn_dc("ON")
        
        return SystemState.LONG_IDLE
    
 
