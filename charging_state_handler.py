import asyncio
import logging
import time
from typing import Optional

from services.ac_recovery import AcRecoveryTask
from services.battery_guard import BatteryGuard
from services.charging_supervisor import ChargingSupervisor, ChargingConfig
from services.failure_streak import FailureStreak
from services.runtime_status import runtime_status_store


def _power_w(power) -> float:
    return float(power) if power is not None else -1


class ChargingState:
    async def handle(self, handler: "ChargingStateHandler"):
        raise NotImplementedError


class WaitPowerState(ChargingState):
    async def handle(self, handler: "ChargingStateHandler"):
        logging.info("Charging: WAIT_POWER - waiting for TAPO offline->online cycle")
        first_launch = handler.first_launch
        try:
            await handler.tapo_controller.get_status()
            tapo_status = handler.tapo_controller.status.get_status()
            is_online = tapo_status.get("online")
        except Exception:
            logging.warning("Charging: TAPO status refresh failed; treating as offline", exc_info=True)
            is_online = False

        if first_launch:
            handler.first_launch = False
            if is_online:
                if await handler.skip_start_if_battery_blocks():
                    await asyncio.sleep(handler.config.check_interval_sec)
                    return
                handler.set_state(StartChargingState(), "First launch with TAPO online")
                return

        if not is_online:
            if not handler.offline_seen_in_wait:
                confirmed = handler.register_offline_failure()
                # React to a possible real outage immediately; only the charge start waits for confirmation.
                await handler.trigger_ac_keep_alive()
                if confirmed:
                    handler.offline_seen_in_wait = True
                    logging.info("Charging: TAPO offline confirmed; will start charging when it returns")
                else:
                    logging.info(
                        "Charging: TAPO poll failed (%s/%s); not treating as disconnected yet",
                        handler.offline_failures,
                        handler.config.offline_confirm_failures,
                    )
            else:
                logging.info("Charging: TAPO offline; waiting to come online")
            await asyncio.sleep(handler.config.check_interval_sec)
            return

        if handler.offline_seen_in_wait:
            if await handler.skip_start_if_battery_blocks():
                handler.offline_seen_in_wait = False
                handler.reset_offline_tracking()
                await asyncio.sleep(handler.config.check_interval_sec)
                return
            handler.reset_offline_tracking()
            handler.set_state(StartChargingState(), "TAPO back online after offline")
            return

        handler.reset_offline_tracking()
        logging.info("Charging: TAPO online but no offline event observed yet; staying in WAIT_POWER")
        await asyncio.sleep(handler.config.check_interval_sec)


class StartChargingState(ChargingState):
    async def handle(self, handler: "ChargingStateHandler"):
        logging.info("Charging: START_CHARGING - turning socket on")
        try:
            await handler.tapo_controller.start_charging()
            await handler.bluetti_controller.initialize()
            handler.bluetti_controller.turn_ac("OFF")
            handler.socket_on_at = time.monotonic()
            handler.first_power_check_at = handler.socket_on_at + handler.config.first_power_check_delay_sec
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
                logging.warning("Charging: Retry power read failed", exc_info=True)
                await handler.trigger_ac_keep_alive()
                if handler.register_monitor_read_failure():
                    handler.set_state(WaitPowerState(), "Power reads failing; treating TAPO as disconnected")
                    handler.offline_seen_in_wait = True
                    return
                logging.info(
                    "Charging: Power read failed (%s/%s); keeping socket state and retrying",
                    handler.monitor_read_failures,
                    handler.config.monitor_read_failures,
                )
                await asyncio.sleep(handler.config.stable_power_interval_sec)
                return

        if handler.monitor_read_failures:
            logging.info("Charging: Power reads recovered after %s failure(s)", handler.monitor_read_failures)
            handler.reset_monitor_read_failures()
            await handler.release_ac_keep_alive()

        is_charging = handler.supervisor.is_charging(power)

        if is_charging:
            handler.stable_checks_remaining = handler.config.stable_power_checks
        else:
            handler.stable_checks_remaining = max(handler.stable_checks_remaining - 1, 0)

        if not is_charging:
            logging.info(
                "Charging: Stable check power=%.2fW (remaining=%s, threshold=%s)",
                _power_w(power),
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

        logging.info(
            "Charging: Power check power=%.2fW threshold=%s elapsed_on=%.1fs",
            _power_w(power),
            handler.config.charging_w_threshold,
            elapsed_on,
        )

        await asyncio.sleep(handler.config.check_interval_sec)


class StopChargingState(ChargingState):
    async def handle(self, handler: "ChargingStateHandler"):
        logging.info("Charging: STOP_CHARGING - turning socket off")
        try:
            await handler.tapo_controller.stop_charging()
        except Exception:
            logging.warning("Charging: Failed to stop charging cleanly", exc_info=True)

        handler.socket_on_at = None
        handler.first_power_check_at = None
        handler.stable_checks_remaining = handler.config.stable_power_checks
        handler.set_state(WaitPowerState(), "Stopped charging; returning to wait")
        await asyncio.sleep(handler.config.check_interval_sec)


class ChargingStateHandler:
    def __init__(
        self,
        tapo_controller,
        bluetti_controller,
        config: Optional[ChargingConfig] = None,
        supervisor: Optional[ChargingSupervisor] = None,
    ):
        self.config = config or ChargingConfig.from_env()
        self.supervisor = supervisor or ChargingSupervisor(self.config)
        self.state: ChargingState = WaitPowerState()
        self.tapo_controller = tapo_controller
        self.bluetti_controller = bluetti_controller
        self.socket_on_at: Optional[float] = None
        self.first_power_check_at: Optional[float] = None
        self.stable_checks_remaining = self.config.stable_power_checks
        self.offline_seen_in_wait = False
        self.offline_streak = FailureStreak(self.config.offline_confirm_failures, self.config.offline_confirm_sec)
        self.ac_keep_alive_sent = False
        self.battery_guard = BatteryGuard(self.config, bluetti_controller, tapo_controller)
        self.monitor_streak = FailureStreak(self.config.monitor_read_failures, self.config.monitor_read_fail_sec)
        self.first_launch = True
        self.ac_recovery = AcRecoveryTask(
            self.config,
            bluetti_controller,
            lambda: isinstance(self.state, WaitPowerState) and self.offline_seen_in_wait,
        )
        runtime_status_store.set_charging_state(self._state_name(self.state))

    @staticmethod
    def _state_name(state: ChargingState) -> str:
        name = state.__class__.__name__
        if name.endswith("State"):
            name = name[:-5]
        return name.upper()

    def set_state(self, state: ChargingState, reason: str | None = None):
        previous_state_name = self._state_name(self.state)
        next_state_name = self._state_name(state)
        logging.info(
            "Charging: State transition %s -> %s%s",
            self.state.__class__.__name__,
            state.__class__.__name__,
            f" ({reason})" if reason else "",
        )
        runtime_status_store.set_charging_transition(previous_state_name, next_state_name, reason)
        self.state = state
        self.reset_monitor_read_failures()
        if isinstance(state, WaitPowerState):
            # Require a fresh offline->online observation each time we re-enter WAIT_POWER
            self.offline_seen_in_wait = False
            self.reset_offline_tracking()
        else:
            self.ac_recovery.cancel()

    @property
    def offline_recovery_task(self) -> Optional[asyncio.Task]:
        return self.ac_recovery.task

    @property
    def offline_failures(self) -> int:
        return self.offline_streak.count

    @property
    def monitor_read_failures(self) -> int:
        return self.monitor_streak.count

    def reset_offline_tracking(self):
        self.offline_streak.reset()
        self.ac_keep_alive_sent = False

    def register_offline_failure(self) -> bool:
        """Record a failed poll; True once the outage is long enough to count as a disconnect."""
        return self.offline_streak.register()

    def register_monitor_read_failure(self) -> bool:
        """Record a failed power read in MONITOR; True once failures are long enough to count as an outage."""
        return self.monitor_streak.register()

    def reset_monitor_read_failures(self):
        self.monitor_streak.reset()

    async def trigger_ac_keep_alive(self):
        """Turn the Bluetti AC on once per outage so a real power cut is covered quickly."""
        if self.ac_keep_alive_sent:
            return
        self.ac_keep_alive_sent = True
        logging.info("Charging: TAPO unreachable; triggering Bluetti AC keep-alive")
        try:
            await self.bluetti_controller.initialize()
            self.bluetti_controller.turn_ac("ON")
        except Exception:
            logging.warning("Charging: Failed to trigger Bluetti AC keep-alive", exc_info=True)
        self.schedule_offline_recovery_check()

    async def release_ac_keep_alive(self):
        """The plug answered again while charging: undo the keep-alive."""
        if not self.ac_keep_alive_sent:
            return
        self.ac_recovery.cancel()
        self.ac_keep_alive_sent = False
        try:
            self.bluetti_controller.turn_ac("OFF")
        except Exception:
            logging.warning("Charging: Failed to turn Bluetti AC off after recovery", exc_info=True)

    async def skip_start_if_battery_blocks(self) -> bool:
        return await self.battery_guard.skip_start_if_battery_blocks()

    async def handle_state(self):
        await self.state.handle(self)

    def schedule_offline_recovery_check(self):
        self.ac_recovery.start()
