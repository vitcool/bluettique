import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from services.bluettiMqtt import BluettiMQTTService
from utils.env import int_env

class BluettiController:
    def __init__(self):
        self.bluetti = BluettiMQTTService()
        self.connection_set = False
        self._watchdog_enabled = False
        self.connection_retry_attempts = int_env(
            "BLUETTI_CONNECTION_RETRY_ATTEMPTS", 1, min_value=1
        )
        self.telemetry_stale_sec = int_env("CONNECTION_WINDOW_MIN", 5, min_value=1) * 60
        self.watchdog_interval_sec = int_env(
            "BLUETTI_WATCHDOG_INTERVAL_SEC", 15, min_value=1
        )
        self.unavailable_retry_sec = int_env(
            "BLUETTI_UNAVAILABLE_RETRY_SEC", 300, min_value=1
        )
        self._initialize_lock = asyncio.Lock()
        self.connection_state_path = Path(
            os.getenv("BLUETTI_CONNECTION_STATE_FILE", "logs/bluetti_connection_state.json")
        )
        self._connection_retry_after = 0.0
        self._connection_blocked = self._load_connection_blocked()

    def _load_connection_blocked(self) -> bool:
        try:
            state = json.loads(self.connection_state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False
        except (OSError, json.JSONDecodeError) as exc:
            logging.warning(
                "Could not read Bluetti connection state file %s: %s",
                self.connection_state_path,
                exc,
            )
            return False
        blocked = bool(state.get("blocked")) if isinstance(state, dict) else False
        if blocked:
            try:
                self._connection_retry_after = float(state.get("retry_after", 0))
            except (TypeError, ValueError):
                self._connection_retry_after = 0.0
            if self._connection_retry_after <= 0:
                self._connection_retry_after = time.time() + self.unavailable_retry_sec
            logging.warning(
                "Bluetti connection retry is paused by saved state in %s until %s.",
                self.connection_state_path,
                datetime.fromtimestamp(self._connection_retry_after, timezone.utc).isoformat(),
            )
        return blocked

    def _save_connection_blocked(self, blocked: bool) -> None:
        self._connection_blocked = blocked
        try:
            if not blocked:
                self._connection_retry_after = 0.0
                self.connection_state_path.unlink(missing_ok=True)
                return
            self._connection_retry_after = time.time() + self.unavailable_retry_sec
            self.connection_state_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "blocked": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "retry_after": self._connection_retry_after,
                "reason": "Bluetti connection attempts exhausted",
            }
            temp_path = self.connection_state_path.with_suffix(
                self.connection_state_path.suffix + ".tmp"
            )
            temp_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            temp_path.replace(self.connection_state_path)
        except OSError:
            logging.exception("Could not persist Bluetti connection state to %s", self.connection_state_path)

    async def initialize(self, force: bool = False):
        async with self._initialize_lock:
            return await self._initialize_locked(force=force)

    async def _initialize_locked(self, force: bool = False):
        if self._connection_blocked:
            if time.time() < self._connection_retry_after and not force:
                logging.info("Bluetti connection is paused until its next scheduled retry.")
                return False
            if force and time.time() < self._connection_retry_after:
                logging.info("Forcing Bluetti reconnect after external power recovery signal.")
            else:
                logging.info("Bluetti retry interval elapsed; trying to connect again.")
            self._connection_blocked = False

        if self.connection_set:
            battery_updated_at = self.bluetti.status.battery_updated_at
            telemetry_fresh = (
                battery_updated_at is not None
                and time.monotonic() - battery_updated_at <= self.telemetry_stale_sec
            )
            broker_running = self.bluetti.is_broker_running()
            if self.bluetti.device_connected and telemetry_fresh and broker_running:
                logging.info("BluettiController already connected; skipping initialize.")
                return True
            if self.bluetti.device_connected or not broker_running:
                logging.warning(
                    "Bluetti connection is unhealthy (broker_running=%s, device_connected=%s, "
                    "telemetry_fresh=%s); resetting and reconnecting.",
                    broker_running,
                    self.bluetti.device_connected,
                    telemetry_fresh,
                )
                self.bluetti.reset_connection()
            else:
                logging.info(
                    "BluettiController flagged connected but device is not; attempting reconnection."
                )
            self.connection_set = False

        logging.info("BluettiController initializing.")
        for attempt in range(1, self.connection_retry_attempts + 1):
            if await self.bluetti.connect():
                logging.info("BluettiMQTTService connected.")
                self.connection_set = True
                self._watchdog_enabled = True
                self._save_connection_blocked(False)
                return True
            if attempt < self.connection_retry_attempts:
                logging.info(
                    "Retrying connection to BluettiMQTTService... (Attempt %s)",
                    attempt + 1,
                )
                await asyncio.sleep(10)

        logging.warning(
            "Bluetti pairing failed after %s controller attempts; resetting the Bluetooth adapter.",
            self.connection_retry_attempts,
        )
        await self.bluetti.reset_bluetooth_adapter()
        logging.info("Retrying Bluetti pairing after the Bluetooth adapter reset.")
        if await self.bluetti.connect():
            logging.info("BluettiMQTTService connected after Bluetooth adapter reset.")
            self.connection_set = True
            self._watchdog_enabled = True
            self._save_connection_blocked(False)
            return True

        logging.error(
            "Bluetti connection failed after retries and adapter reset; "
            "pausing until the next scheduled retry."
        )
        self.connection_set = False
        self._watchdog_enabled = False
        self._save_connection_blocked(True)
        return False

    async def monitor_connection(self, monitoring_enabled: Callable[[], bool] | None = None):
        """Retry unavailable Bluetti connections and recover links that later drop."""
        monitoring_enabled = monitoring_enabled or (lambda: True)
        previously_enabled = monitoring_enabled()
        while True:
            await asyncio.sleep(self.watchdog_interval_sec)
            enabled = monitoring_enabled()
            if not enabled:
                if self.connection_set or self._watchdog_enabled:
                    self.stop()
                previously_enabled = False
                continue
            if not previously_enabled:
                await self.initialize(force=True)
                previously_enabled = True
                continue
            if self._connection_blocked:
                if time.time() >= self._connection_retry_after:
                    await self.initialize()
                continue
            if not self._watchdog_enabled:
                continue

            battery_updated_at = self.bluetti.status.battery_updated_at
            telemetry_fresh = (
                battery_updated_at is not None
                and time.monotonic() - battery_updated_at <= self.telemetry_stale_sec
            )
            broker_running = self.bluetti.is_broker_running()
            if self.bluetti.device_connected and telemetry_fresh and broker_running:
                continue

            logging.warning(
                "Bluetti watchdog detected lost connection (broker_running=%s, "
                "device_connected=%s, telemetry_fresh=%s); reconnecting.",
                broker_running,
                self.bluetti.device_connected,
                telemetry_fresh,
            )
            await self.initialize()

    def turn_dc(self, state: str):
        logging.info(f"Bluetti: Turning DC device {state}")
        self.bluetti.set_dc_output(state)

    def turn_ac(self, state: str):
        logging.info(f"Bluetti: Turning AC device {state}")
        self.bluetti.set_ac_output(state)

    def power_off(self):
        logging.info("Bluetti: Turning off device")
        # self.bluetti.power_off() sometimes it works, sometimes it doesn't
        self.stop()
        # self.bluetti.reset_status()
        self.connection_set = False
        self._watchdog_enabled = False
        self.bluetti.status.reset_output_status()

    async def power_off_until_confirmed(self, max_attempts: int, quiet_sec: float) -> bool:
        """Send the power-off command until telemetry has been silent for quiet_sec; True once confirmed."""
        poll_sec = min(5.0, quiet_sec)
        for attempt in range(1, max_attempts + 1):
            if not await self.initialize():
                logging.warning("Bluetti is unavailable; cannot send power-off command.")
                return False
            logging.info(f"Bluetti: Power off command (attempt {attempt}/{max_attempts})")
            self.bluetti.power_off()
            deadline = time.monotonic() + quiet_sec * 2
            while time.monotonic() < deadline:
                await asyncio.sleep(poll_sec)
                updated_at = self.bluetti.status.battery_updated_at
                if updated_at is None or time.monotonic() - updated_at >= quiet_sec:
                    logging.info("Bluetti: Power off confirmed (no telemetry for %.0fs)", quiet_sec)
                    self.power_off()
                    return True
            logging.warning(f"Bluetti: Still sending telemetry after power off (attempt {attempt}/{max_attempts})")
        return False

    def get_status(self):
        return self.bluetti.status.get_status()

    def stop(self):
        logging.info("Bluetti: Stopping MQTT client and broker")
        self._watchdog_enabled = False
        self.bluetti.stop_client()
        self.bluetti.stop_broker()
        self.bluetti.disconnect_device()
        self.connection_set = False
