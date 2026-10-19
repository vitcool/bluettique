import asyncio
import logging
import time
from typing import Optional

from services.charging_supervisor import ChargingSupervisor, ChargingConfig
from services.runtime_status import runtime_status_store


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

        logging.info(
            "Charging: Power check power=%.2fW threshold=%s elapsed_on=%.1fs",
            float(power) if power is not None else -1,
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
        self.offline_failures = 0
        self.offline_since: Optional[float] = None
        self.ac_keep_alive_sent = False
        self.monitor_read_failures = 0
        self.monitor_fail_since: Optional[float] = None
        self.first_launch = True
        self.offline_recovery_task: Optional[asyncio.Task] = None
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
            if self.offline_recovery_task and not self.offline_recovery_task.done():
                self.offline_recovery_task.cancel()
                self.offline_recovery_task = None

    def reset_offline_tracking(self):
        self.offline_failures = 0
        self.offline_since = None
        self.ac_keep_alive_sent = False

    def register_offline_failure(self) -> bool:
        """Record a failed poll; True once the outage is long enough to count as a disconnect."""
        now = time.monotonic()
        if self.offline_since is None:
            self.offline_since = now
        self.offline_failures += 1
        return (
            self.offline_failures >= self.config.offline_confirm_failures
            or now - self.offline_since >= self.config.offline_confirm_sec
        )

    def register_monitor_read_failure(self) -> bool:
        """Record a failed power read in MONITOR; True once failures are long enough to count as an outage."""
        now = time.monotonic()
        if self.monitor_fail_since is None:
            self.monitor_fail_since = now
        self.monitor_read_failures += 1
        return (
            self.monitor_read_failures >= self.config.monitor_read_failures
            or now - self.monitor_fail_since >= self.config.monitor_read_fail_sec
        )

    def reset_monitor_read_failures(self):
        self.monitor_read_failures = 0
        self.monitor_fail_since = None

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
        if self.offline_recovery_task and not self.offline_recovery_task.done():
            self.offline_recovery_task.cancel()
            self.offline_recovery_task = None
        self.ac_keep_alive_sent = False
        try:
            self.bluetti_controller.turn_ac("OFF")
        except Exception:
            logging.warning("Charging: Failed to turn Bluetti AC off after recovery", exc_info=True)

    def _read_battery_percent(self) -> Optional[float]:
        """Latest known battery percent, or None when missing, unreadable or older than the allowed age."""
        try:
            status = self.bluetti_controller.get_status()
        except Exception:
            logging.warning("Charging: Could not read Bluetti status", exc_info=True)
            return None
        percent = status.get("total_battery_percent")
        if percent is None:
            return None
        updated_at = status.get("battery_updated_at")
        max_age = self.config.battery_max_age_sec
        if updated_at is not None and max_age > 0 and time.monotonic() - updated_at > max_age:
            return None
        try:
            return float(percent)
        except (TypeError, ValueError):
            return None

    async def _wait_for_battery_percent(self) -> Optional[float]:
        """Give the Bluetti a short window to report a fresh level (e.g. right after a restart)."""
        percent = self._read_battery_percent()
        if percent is not None or self.config.battery_unknown_wait_sec <= 0:
            return percent
        try:
            await self.bluetti_controller.initialize()
        except Exception:
            logging.warning("Charging: Bluetti initialize failed while waiting for battery level", exc_info=True)
        # initialize() can itself take a long time, so the window starts after it returns
        deadline = time.monotonic() + self.config.battery_unknown_wait_sec
        percent = self._read_battery_percent()
        while percent is None and time.monotonic() < deadline:
            await asyncio.sleep(1)
            percent = self._read_battery_percent()
        return percent

    async def skip_start_if_battery_blocks(self) -> bool:
        """True (and socket forced off) when charging must not start: battery full, or level unknown."""
        percent = await self._wait_for_battery_percent()
        limit = self.config.charge_skip_above_percent
        if percent is None:
            if not self.config.charge_skip_when_unknown:
                logging.info("Charging: Bluetti battery level unknown; not blocking start")
                return False
            logging.info("Charging: Bluetti battery level unknown or stale; not starting charging")
        elif percent >= limit:
            logging.info("Charging: Bluetti battery %s%% >= %s%%; not starting charging", percent, limit)
        else:
            return False
        try:
            await self.tapo_controller.stop_charging()
        except Exception:
            logging.warning("Charging: Failed to turn socket off while skipping start", exc_info=True)
        return True

    async def handle_state(self):
        await self.state.handle(self)

    def schedule_offline_recovery_check(self):
        if self.offline_recovery_task and not self.offline_recovery_task.done():
            self.offline_recovery_task.cancel()

        async def _delayed_check():
            try:
                poll_interval = self.config.stable_power_interval_sec
                zero_duration = 0.0
                ac_retry_attempts = 0
                ac_retry_limit_logged = False
                ac_retry_suppressed_after_zero_off = False
                ac_retry_suppressed_logged = False
                retry_interval = max(float(self.config.ac_retry_interval_sec), 0.1)
                max_retries = int(self.config.ac_retry_max_attempts)
                last_retry_at = 0.0

                while True:
                    await asyncio.sleep(poll_interval)
                    status = self.bluetti_controller.get_status()
                    ac_on = status.get("ac_output_on")
                    ac_power = status.get("ac_output_power")

                    if not ac_on:
                        in_wait_power = isinstance(self.state, WaitPowerState)
                        should_retry = (
                            in_wait_power
                            and self.offline_seen_in_wait
                            and not ac_retry_suppressed_after_zero_off
                        )
                        retries_allowed = max_retries <= 0 or ac_retry_attempts < max_retries
                        now = time.monotonic()

                        if should_retry and retries_allowed and now - last_retry_at >= retry_interval:
                            ac_retry_attempts += 1
                            last_retry_at = now
                            limit_display = "unlimited" if max_retries <= 0 else str(max_retries)
                            logging.info(
                                "Charging: AC output is OFF; retrying AC ON (%s/%s)",
                                ac_retry_attempts,
                                limit_display,
                            )
                            try:
                                await self.bluetti_controller.initialize()
                                self.bluetti_controller.turn_ac("ON")
                            except Exception:
                                logging.warning("Charging: AC ON retry failed", exc_info=True)

                        if should_retry and not retries_allowed and not ac_retry_limit_logged:
                            logging.warning(
                                "Charging: AC output still OFF after %s retries; will not retry again",
                                max_retries,
                            )
                            ac_retry_limit_logged = True

                        if ac_retry_suppressed_after_zero_off and not ac_retry_suppressed_logged:
                            logging.info(
                                "Charging: AC retries suppressed after zero-power auto-off; waiting for next cycle",
                            )
                            ac_retry_suppressed_logged = True

                        zero_duration = 0.0
                        continue

                    if ac_retry_attempts:
                        logging.info(
                            "Charging: AC output confirmed ON after %s retries",
                            ac_retry_attempts,
                        )
                    ac_retry_attempts = 0
                    ac_retry_limit_logged = False

                    try:
                        power_val = float(ac_power) if ac_power is not None else 0.0
                    except (TypeError, ValueError):
                        power_val = 0.0

                    if power_val <= 0.0:
                        zero_duration += poll_interval
                        if zero_duration >= self.config.ac_zero_power_off_sec:
                            logging.info(
                                "Charging: Offline recovery turning AC off after %.0fs at ~0W draw",
                                zero_duration,
                            )
                            self.bluetti_controller.turn_ac("OFF")
                            ac_retry_suppressed_after_zero_off = True
                            ac_retry_suppressed_logged = False
                            ac_retry_attempts = 0
                            ac_retry_limit_logged = False
                            zero_duration = 0.0
                    else:
                        ac_retry_suppressed_after_zero_off = False
                        ac_retry_suppressed_logged = False
                        zero_duration = 0.0
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.warning("Charging: Offline recovery check failed", exc_info=True)

        self.offline_recovery_task = asyncio.create_task(_delayed_check())
