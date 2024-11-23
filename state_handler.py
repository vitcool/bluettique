import asyncio
import os
import logging
import psutil
from models.system_state import SystemState


async def handle_state(
    state: SystemState, tapo_controller, bluetti_controller, fingerbot_controller
) -> SystemState:
    logging.info(f"Handle {state} state")
    is_dev_env = os.getenv("ENV") == "dev"
    is_prod_env = os.getenv("ENV") == "prod"

    if state == SystemState.INITIAL_CHECK:
        """May be repalced in the future if bluetti params are stored in a file"""
        if not bluetti_controller.connection_set:
            await fingerbot_controller.press_button()
            await bluetti_controller.initialize()

        while not bluetti_controller.get_status().get("info_received"):
            await asyncio.sleep(5)

        return SystemState.CHECK_STATUS

    elif state == SystemState.IDLE:
        await asyncio.sleep(int(os.getenv("IDLE_INTERVAL")))
        logging.info(f"Memory usage: {psutil.virtual_memory().percent}%")
        logging.info(f"CPU usage: {psutil.cpu_percent()}%")
        return SystemState.CHECK_STATUS

    elif state == SystemState.LONG_IDLE:
        await asyncio.sleep(int(os.getenv("LONG_IDLE_INTERVAL")))
        return SystemState.CHECK_STATUS

    elif state == SystemState.CHECK_STATUS:
        await tapo_controller.get_status()
        tapo_status = tapo_controller.status.get_status()
        bluetti_status = bluetti_controller.get_status()

        is_tapo_online = tapo_status.get("online")
        is_tapo_charing = tapo_status.get("charging")

        total_battery_percent_bluetti = bluetti_status.get("total_battery_percent")
        ac_output_on_bluetti = bluetti_status.get("ac_output_on")
        dc_output_on_bluetti = bluetti_status.get("dc_output_on")
        ac_output_power_bluetti = bluetti_status.get("ac_output_power")
        dc_output_power_bluetti = bluetti_status.get("dc_output_power")

        logging.info(f"AC output power: {ac_output_power_bluetti}")
        logging.info(f"DC output power: {dc_output_power_bluetti}")
        logging.info(f"bluetti_controller.turned_on: {bluetti_controller.turned_on}")
        logging.info(f"bluetti_controller.ac_turned_on: {bluetti_controller.ac_turned_on}")
        logging.info(f"bluetti_controller.dc_turned_on: {bluetti_controller.dc_turned_on}")
        logging.info(f"bluetti_controller.total_battery_percent_bluetti: {total_battery_percent_bluetti}")
        logging.info(f"ac_output_on_bluetti: {ac_output_on_bluetti}")
        logging.info(f"dc_output_on_bluetti: {dc_output_on_bluetti}")
        logging.info(f"is_tapo_charing: {is_tapo_charing}")
        logging.info(f"is_tapo_online: {is_tapo_online}")

        if (
            is_tapo_online
            and not is_tapo_charing
            and total_battery_percent_bluetti < 100
        ):
            return SystemState.START_CHARGING

        if is_tapo_charing and total_battery_percent_bluetti == 100:
            return SystemState.STOP_CHARGING

        if not is_tapo_online and not ac_output_on_bluetti and not dc_output_on_bluetti:
            return SystemState.TURN_AC_ON

        if (
            bluetti_controller.turned_on
            and ac_output_power_bluetti == 0
            and dc_output_power_bluetti == 0
            and not is_tapo_charing
        ):
            return SystemState.TURN_OFF
        
        if (ac_output_on_bluetti and ac_output_power_bluetti > 0):
            return SystemState.TURN_DC_OFF

        return SystemState.IDLE

    elif state == SystemState.START_CHARGING:
        await tapo_controller.start_charging()
        if is_dev_env and bluetti_controller.dc_turned_on:
            bluetti_controller.turn_dc("OFF")

        if is_prod_env and bluetti_controller.ac_turned_on:
            bluetti_controller.turn_ac("OFF")

        return SystemState.IDLE

    elif state == SystemState.STOP_CHARGING:
        await tapo_controller.stop_charging()

        return SystemState.TURN_OFF

    elif state == SystemState.TURN_OFF:
        bluetti_controller.power_off()
        await fingerbot_controller.press_button(False)

        return SystemState.IDLE

    elif state == SystemState.TURN_AC_ON:
        if not bluetti_controller.turned_on or not bluetti_controller.connection_set:
            await fingerbot_controller.press_button()
            await bluetti_controller.initialize()

        if is_prod_env and not bluetti_controller.ac_turned_on:
            bluetti_controller.turn_ac("ON")
            await asyncio.sleep(2)
            bluetti_controller.turn_dc("ON")
            await asyncio.sleep(2)

        if is_dev_env and not bluetti_controller.dc_turned_on:
            bluetti_controller.turn_dc("ON")

        return SystemState.IDLE
    
    elif state == SystemState.TURN_DC_OFF:
        bluetti_controller.turn_dc("OFF")
        
        return SystemState.LONG_IDLE
