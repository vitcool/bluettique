import asyncio
import os
import logging
import psutil
import datetime

class State:
    async def handle(self, handler, tapo_controller, bluetti_controller, fingerbot_controller, schedule_manager):
        raise NotImplementedError

class InitialCheckState(State):
    async def handle(self, handler, tapo_controller, bluetti_controller, fingerbot_controller, schedule_manager):
        logging.info("Handle INITIAL_CHECK state")
        if not bluetti_controller.connection_set:
            await fingerbot_controller.press_button()
            await bluetti_controller.initialize()
            while not bluetti_controller.get_status().get("info_received"):
                await asyncio.sleep(5)
        handler.set_state(CheckStatusState())

class IdleState(State):
    async def handle(self, handler, tapo_controller, bluetti_controller, fingerbot_controller, schedule_manager):
        outage_expected = schedule_manager.is_outage_expected()
        delay = 0
        
        if (outage_expected and not bluetti_controller.ac_turned_on):
            delay = handler.idle_interval
            
        if (not outage_expected or bluetti_controller.ac_turned_on):
            current_time = datetime.datetime.now()
            time_to_end_of_hour = (60 - current_time.minute) * 60 - current_time.second
            
            if time_to_end_of_hour < handler.long_idle_interval:
                delay = time_to_end_of_hour
            else:
                delay = handler.long_idle_interval
                
        logging.info(f"Handle IDLE state: outage_expected: {outage_expected}, bluetti_controller.ac_turned_on: {bluetti_controller.ac_turned_on}, delay: {delay}s")

        await asyncio.sleep(delay)
            
        logging.info(f"Memory usage: {psutil.virtual_memory().percent}%")
        logging.info(f"CPU usage: {psutil.cpu_percent()}%")
        handler.set_state(CheckStatusState())

class CheckStatusState(State):
    async def handle(self, handler, tapo_controller, bluetti_controller, fingerbot_controller, schedule_manager):
        logging.info("Handle CHECK_STATUS state")
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
        logging.info(f"is_turned_off_because_unused: {handler.is_turned_off_because_unused}")

        next_state = IdleState()

        if is_tapo_online or (ac_output_on_bluetti and ac_output_power_bluetti > 0):
            handler.is_turned_off_because_unused = False

        if is_tapo_online and not is_tapo_charing and total_battery_percent_bluetti < 100:
            next_state = StartChargingState()

        if is_tapo_charing and total_battery_percent_bluetti == 100:
            next_state = StopChargingState()

        if not is_tapo_online and not ac_output_on_bluetti and not dc_output_on_bluetti and not handler.is_turned_off_because_unused:
            next_state = TurnAcOnState()

        if bluetti_controller.turned_on and ac_output_power_bluetti == 0 and dc_output_power_bluetti <= 10 and not is_tapo_online:
            handler.is_turned_off_because_unused = True
            next_state = TurnOffState()

        if ac_output_on_bluetti and ac_output_power_bluetti > 0 and dc_output_on_bluetti:
            next_state = TurnDcOffState()
            
        if is_tapo_online and total_battery_percent_bluetti == 100 and not ac_output_on_bluetti:
            next_state = TurnOffState()
            
        logging.info(f"Next state: {next_state}")
        handler.set_state(next_state)

class StartChargingState(State):
    async def handle(self, handler, tapo_controller, bluetti_controller, fingerbot_controller, schedule_manager):
        logging.info("Handle START_CHARGING state")
        await tapo_controller.start_charging()
        if handler.is_dev_env and bluetti_controller.dc_turned_on:
            bluetti_controller.turn_dc("OFF")
        if bluetti_controller.ac_turned_on:
            bluetti_controller.turn_ac("OFF")
        handler.set_state(IdleState())

class StopChargingState(State):
    async def handle(self, handler, tapo_controller, bluetti_controller, fingerbot_controller, schedule_manager):
        logging.info("Handle STOP_CHARGING state")
        await tapo_controller.stop_charging()
        handler.set_state(TurnOffState())

class TurnOffState(State):
    async def handle(self, handler, tapo_controller, bluetti_controller, fingerbot_controller, schedule_manager):
        logging.info("Handle TURN_OFF state")
        bluetti_controller.power_off()
        await fingerbot_controller.press_button(False)
        handler.set_state(IdleState())

class TurnAcOnState(State):
    async def handle(self, handler, tapo_controller, bluetti_controller, fingerbot_controller, schedule_manager):
        logging.info("Handle TURN_AC_ON state")
        handler.is_turned_off_because_unused = False
        if not bluetti_controller.turned_on or not bluetti_controller.connection_set:
            await fingerbot_controller.press_button()
            await bluetti_controller.initialize()
        if not bluetti_controller.ac_turned_on:
            bluetti_controller.turn_ac("ON")
            await asyncio.sleep(2)
            bluetti_controller.turn_dc("ON")
            await asyncio.sleep(2)
        if handler.is_dev_env and not bluetti_controller.dc_turned_on:
            bluetti_controller.turn_dc("ON")
        handler.set_state(IdleState())

class TurnDcOffState(State):
    async def handle(self, handler, tapo_controller, bluetti_controller, fingerbot_controller, schedule_manager):
        logging.info("Handle TURN_DC_OFF state")
        bluetti_controller.turn_dc("OFF")
        handler.set_state(IdleState())
        
class StateHandler:
    def __init__(self):
        self.is_turned_off_because_unused = False
        self.is_dev_env = os.getenv("ENV") == "dev"
        self.is_prod_env = os.getenv("ENV") == "prod"
        self.idle_interval = int(os.getenv("IDLE_INTERVAL"))
        self.long_idle_interval = int(os.getenv("LONG_IDLE_INTERVAL"))
        self.state = InitialCheckState()

    def set_state(self, state):
        self.state = state

    async def handle_state(self, tapo_controller, bluetti_controller, fingerbot_controller, schedule_manager):
        await self.state.handle(self, tapo_controller, bluetti_controller, fingerbot_controller, schedule_manager)
