import asyncio
import logging
import time
from typing import Optional

from services.charging_supervisor import ChargingConfig


class BatteryGuard:
    def __init__(self, config: ChargingConfig, bluetti_controller, tapo_controller):
        self.config = config
        self.bluetti_controller = bluetti_controller
        self.tapo_controller = tapo_controller

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
