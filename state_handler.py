import asyncio
import os
from models.system_state import SystemState


async def handle_state(
    state: SystemState, tapo_controller, bluetti_controller, fingerbot_controller
) -> SystemState:
    print("Handle ", state, " state")
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

        if is_dev_env:
            print("AC output power: ", ac_output_power_bluetti)
            print("DC output power: ", dc_output_power_bluetti)
            print("bluetti_controller.turned_on: ", bluetti_controller.turned_on)
            print("bluetti_controller.ac_turned_on: ", bluetti_controller.ac_turned_on)
            print("bluetti_controller.dc_turned_on: ", bluetti_controller.dc_turned_on)
            print("ac_output_on_bluetti: ", ac_output_on_bluetti)
            print("dc_output_on_bluetti: ", dc_output_on_bluetti)
            print("is_tapo_charing: ", is_tapo_charing)
            print("is_tapo_online: ", is_tapo_online)

        # if (
        #     is_tapo_online
        #     and not is_tapo_charing
        #     and total_battery_percent_bluetti < 100
        # ):
        #     return SystemState.START_CHARGING

        # if is_tapo_charing and total_battery_percent_bluetti == 100:
        #     return SystemState.STOP_CHARGING

        if is_tapo_charing and not ac_output_on_bluetti and not dc_output_on_bluetti:
            return SystemState.TURN_AC_ON

        if (
            bluetti_controller.turned_on
            and not is_tapo_charing
        ):
            return SystemState.TURN_OFF

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
        await fingerbot_controller.press_button()

        return SystemState.IDLE

    elif state == SystemState.TURN_AC_ON:
        if not bluetti_controller.turned_on or not bluetti_controller.connection_set:
            await fingerbot_controller.press_button()
            await bluetti_controller.initialize()

        if is_prod_env and not bluetti_controller.ac_turned_on:
            bluetti_controller.turn_ac("ON")
            await asyncio.sleep(2)

        if is_dev_env and not bluetti_controller.dc_turned_on:
            bluetti_controller.turn_dc("ON")

        return SystemState.LONG_IDLE
