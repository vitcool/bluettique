import asyncio
import logging
import time
from typing import Optional

from services.charging_supervisor import ChargingSupervisor, ChargingConfig


class ChargingState:
    async def handle(self, handler: "ChargingStateHandler"):
        raise NotImplementedError


class WaitPowerState(ChargingState):
    async def handle(self, handler: "ChargingStateHandler"):
        logging.info("Charging: WAIT_POWER - waiting for TAPO offline->online cycle")
        try:
            await handler.tapo_controller.get_status()
            tapo_status = handler.tapo_controller.status.get_status()
            is_online = tapo_status.get("online")
        except Exception:
            logging.warning("Charging: TAPO status refresh failed; treating as offline", exc_info=True)
            is_online = False

        if not is_online:
            handler.offline_seen_in_wait = True
            logging.info("Charging: TAPO offline; waiting to come online")
            await asyncio.sleep(handler.config.check_interval_sec)
            return

        if handler.offline_seen_in_wait:
            handler.low_power_counter = 0
            handler.stable_checks_remaining = handler.config.stable_power_checks
            handler.set_state(StartChargingState(), "TAPO back online after offline")
            return

        logging.info("Charging: TAPO online but no offline event observed yet; staying in WAIT_POWER")
        await asyncio.sleep(handler.config.check_interval_sec)


class StartChargingState(ChargingState):
    async def handle(self, handler: "ChargingStateHandler"):
        logging.info("Charging: START_CHARGING - turning socket on")
        try:
            await handler.tapo_controller.start_charging()
            handler.socket_on_at = time.monotonic()
            handler.first_power_check_at = handler.socket_on_at + handler.config.first_power_check_delay_sec
            handler.low_power_counter = 0
            handler.stable_checks_remaining = handler.config.stable_power_checks
            handler.set_state(MonitorChargingState(), "Socket turned on")
        except Exception:
            logging.warning("Charging: Failed to start charging, returning to WAIT_POWER", exc_info=True)
            handler.set_state(WaitPowerState(), "Start failed")
            await asyncio.sleep(handler.config.check_interval_sec)


class MonitorChargingState(ChargingState):
    async def handle(self, handler: "ChargingStateHandler"):
        if handler.socket_on_at is None:
            logging.info("Charging: No socket_on_at timestamp, restarting flow")
            handler.set_state(StartChargingState(), "Missing timestamp")
            return

        now = time.monotonic()
        elapsed_on = now - handler.socket_on_at

        if handler.first_power_check_at is not None:
            remaining = handler.first_power_check_at - now
            if remaining > 0:
                logging.info("Charging: Waiting %.1fs before first power check", remaining)
                await asyncio.sleep(min(handler.config.check_interval_sec, remaining))
                return
            handler.first_power_check_at = None

        try:
            power = await handler.tapo_controller.get_current_power()
        except Exception:
            logging.warning("Charging: Power read failed; reinitializing and retrying", exc_info=True)
            try:
                await handler.tapo_controller.initialize()
                power = await handler.tapo_controller.get_current_power()
            except Exception:
                logging.warning("Charging: Retry power read failed, returning to WAIT_POWER", exc_info=True)
                handler.set_state(WaitPowerState(), "Power read failed after retry")
                return

        is_charging = handler.supervisor.is_charging(power)

        if is_charging:
            handler.stable_checks_remaining = handler.config.stable_power_checks
        else:
            handler.stable_checks_remaining = max(handler.stable_checks_remaining - 1, 0)

        if not is_charging:
            logging.info(
                "Charging: Stable check power=%.2fW (remaining=%s, threshold=%s)",
                float(power) if power is not None else -1,
                handler.stable_checks_remaining,
                handler.config.charging_w_threshold,
            )
            if handler.stable_checks_remaining == 0:
                handler.set_state(StopChargingState(), "Stable checks completed below threshold")
                return
            await asyncio.sleep(handler.config.stable_power_interval_sec)
            return

        if elapsed_on < handler.config.startup_grace_sec:
            remaining = handler.config.startup_grace_sec - elapsed_on
            logging.info("Charging: In startup grace (%.1fs remaining)", remaining)
            await asyncio.sleep(min(handler.config.check_interval_sec, remaining))
            return

        if is_charging:
            handler.low_power_counter = 0
        else:
            handler.low_power_counter += 1

        logging.info(
            "Charging: Power check power=%.2fW threshold=%s low_counter=%s elapsed_on=%.1fs",
            float(power) if power is not None else -1,
            handler.config.charging_w_threshold,
            handler.low_power_counter,
            elapsed_on,
        )

        if handler.supervisor.should_stop(power, handler.low_power_counter, elapsed_on):
            handler.set_state(RecheckState(), "Low power sustained, triggering recheck")
            return

        await asyncio.sleep(handler.config.check_interval_sec)


class RecheckState(ChargingState):
    async def handle(self, handler: "ChargingStateHandler"):
        if not handler.config.recheck_cycle_enabled:
            handler.set_state(StopChargingState(), "Recheck disabled; stopping after low power")
            return

        logging.info("Charging: RECHECK - cycling socket for verification")
        try:
            await handler.tapo_controller.stop_charging()
        except Exception:
            logging.warning("Charging: Failed to turn off during recheck", exc_info=True)

        await asyncio.sleep(handler.config.recheck_off_sec)

        try:
            await handler.tapo_controller.start_charging()
            handler.socket_on_at = time.monotonic()
            handler.first_power_check_at = handler.socket_on_at + handler.config.first_power_check_delay_sec
        except Exception:
            logging.warning("Charging: Failed to turn on during recheck, returning to WAIT_POWER", exc_info=True)
            handler.set_state(WaitPowerState(), "Recheck restart failed")
            return

        quick_readings = []
        for idx in range(handler.config.recheck_quick_checks):
            await asyncio.sleep(handler.config.recheck_quick_interval_sec)
            try:
                power = await handler.tapo_controller.get_current_power()
                quick_readings.append(power)
                logging.info(
                    "Charging: Recheck [%s/%s] power=%.2fW threshold=%s",
                    idx + 1,
                    handler.config.recheck_quick_checks,
                    float(power) if power is not None else -1,
                    handler.config.charging_w_threshold,
                )
                if handler.supervisor.is_charging(power):
                    handler.low_power_counter = 0
                    handler.stable_checks_remaining = handler.config.stable_power_checks
                    handler.set_state(MonitorChargingState(), "Charging detected during recheck")
                    return
            except Exception:
                logging.warning("Charging: Recheck power read failed", exc_info=True)
                handler.set_state(WaitPowerState(), "Recheck power read failed")
                return

        keep_charging = handler.supervisor.recheck_confirms_charging(quick_readings)
        if keep_charging:
            handler.low_power_counter = 0
            handler.stable_checks_remaining = handler.config.stable_power_checks
            handler.set_state(MonitorChargingState(), "Recheck kept charging")
            return

        handler.set_state(StopChargingState(), "Recheck confirmed low power")


class StopChargingState(ChargingState):
    async def handle(self, handler: "ChargingStateHandler"):
        logging.info("Charging: STOP_CHARGING - turning socket off")
        try:
            await handler.tapo_controller.stop_charging()
        except Exception:
            logging.warning("Charging: Failed to stop charging cleanly", exc_info=True)

        handler.low_power_counter = 0
        handler.socket_on_at = None
        handler.first_power_check_at = None
        handler.stable_checks_remaining = handler.config.stable_power_checks
        handler.set_state(WaitPowerState(), "Stopped charging; returning to wait")
        await asyncio.sleep(handler.config.check_interval_sec)


class ChargingStateHandler:
    def __init__(
        self,
        tapo_controller,
        config: Optional[ChargingConfig] = None,
        supervisor: Optional[ChargingSupervisor] = None,
    ):
        self.config = config or ChargingConfig.from_env()
        self.supervisor = supervisor or ChargingSupervisor(self.config)
        self.state: ChargingState = WaitPowerState()
        self.tapo_controller = tapo_controller
        self.low_power_counter = 0
        self.socket_on_at: Optional[float] = None
        self.first_power_check_at: Optional[float] = None
        self.stable_checks_remaining = self.config.stable_power_checks
        self.offline_seen_in_wait = False

    def set_state(self, state: ChargingState, reason: str | None = None):
        logging.info(
            "Charging: State transition %s -> %s%s",
            self.state.__class__.__name__,
            state.__class__.__name__,
            f" ({reason})" if reason else "",
        )
        self.state = state
        if isinstance(state, WaitPowerState):
            # Require a fresh offline->online observation each time we re-enter WAIT_POWER
            self.offline_seen_in_wait = False

    async def handle_state(self):
        await self.state.handle(self)
