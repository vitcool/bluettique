import asyncio
import logging
import time
from typing import Callable, Optional

from services.charging_supervisor import ChargingConfig


class AcRecoveryTask:
    """Background watcher that keeps the Bluetti AC on during an outage and turns it off once it draws ~0W."""

    def __init__(self, config: ChargingConfig, bluetti_controller, retries_wanted: Callable[[], bool]):
        self.config = config
        self.bluetti_controller = bluetti_controller
        self.retries_wanted = retries_wanted
        self.task: Optional[asyncio.Task] = None
        self._reset_counters()

    def _reset_counters(self):
        self.zero_duration = 0.0
        self.retry_attempts = 0
        self.retry_limit_logged = False
        self.retry_suppressed_after_zero_off = False
        self.retry_suppressed_logged = False
        self.last_retry_at = 0.0

    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self):
        if self.is_running():
            self.task.cancel()
        self._reset_counters()
        self.task = asyncio.create_task(self._run())

    def cancel(self):
        if self.is_running():
            self.task.cancel()
            self.task = None

    async def _run(self):
        try:
            poll_interval = self.config.stable_power_interval_sec
            while True:
                await asyncio.sleep(poll_interval)
                status = self.bluetti_controller.get_status()
                if not status.get("ac_output_on"):
                    await self._handle_ac_off()
                else:
                    self._handle_ac_on(status.get("ac_output_power"), poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.warning("Charging: Offline recovery check failed", exc_info=True)

    async def _handle_ac_off(self):
        max_retries = int(self.config.ac_retry_max_attempts)
        retry_interval = max(float(self.config.ac_retry_interval_sec), 0.1)
        should_retry = self.retries_wanted() and not self.retry_suppressed_after_zero_off
        retries_allowed = max_retries <= 0 or self.retry_attempts < max_retries
        now = time.monotonic()

        if should_retry and retries_allowed and now - self.last_retry_at >= retry_interval:
            self.retry_attempts += 1
            self.last_retry_at = now
            limit_display = "unlimited" if max_retries <= 0 else str(max_retries)
            logging.info(
                "Charging: AC output is OFF; retrying AC ON (%s/%s)",
                self.retry_attempts,
                limit_display,
            )
            try:
                await self.bluetti_controller.initialize()
                self.bluetti_controller.turn_ac("ON")
            except Exception:
                logging.warning("Charging: AC ON retry failed", exc_info=True)

        if should_retry and not retries_allowed and not self.retry_limit_logged:
            logging.warning(
                "Charging: AC output still OFF after %s retries; will not retry again",
                max_retries,
            )
            self.retry_limit_logged = True

        if self.retry_suppressed_after_zero_off and not self.retry_suppressed_logged:
            logging.info(
                "Charging: AC retries suppressed after zero-power auto-off; waiting for next cycle",
            )
            self.retry_suppressed_logged = True

        self.zero_duration = 0.0

    def _handle_ac_on(self, ac_power, poll_interval):
        if self.retry_attempts:
            logging.info(
                "Charging: AC output confirmed ON after %s retries",
                self.retry_attempts,
            )
        self.retry_attempts = 0
        self.retry_limit_logged = False

        try:
            power_val = float(ac_power) if ac_power is not None else 0.0
        except (TypeError, ValueError):
            power_val = 0.0

        if power_val > 0.0:
            self.retry_suppressed_after_zero_off = False
            self.retry_suppressed_logged = False
            self.zero_duration = 0.0
            return

        self.zero_duration += poll_interval
        if self.zero_duration >= self.config.ac_zero_power_off_sec:
            logging.info(
                "Charging: Offline recovery turning AC off after %.0fs at ~0W draw",
                self.zero_duration,
            )
            self.bluetti_controller.turn_ac("OFF")
            self.retry_suppressed_after_zero_off = True
            self.retry_suppressed_logged = False
            self.retry_attempts = 0
            self.retry_limit_logged = False
            self.zero_duration = 0.0
