import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from typing import Optional, Tuple

from services.tapo import TapoService


# Lightweight clock wrapper to ease testing.
class Clock:
    def now(self) -> datetime:
        return datetime.now()

    def monotonic(self) -> float:
        return time.monotonic()


def _parse_time(val: str, default: str) -> dtime:
    raw = (val or default).strip()
    try:
        hours, minutes = [int(part) for part in raw.split(":")]
        return dtime(hour=hours, minute=minutes)
    except Exception:
        return _parse_time(default, default) if val != default else dtime(0, 0)


def _ensure_dir(path: str):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)


@dataclass
class BoilerConfig:
    enabled: bool
    username: Optional[str]
    password: Optional[str]
    ip_address: Optional[str]
    window_start: dtime
    window_end: dtime
    total_run_sec: int
    poll_sec: int
    active_w_threshold: float
    state_file: str
    log_file: str

    @classmethod
    def from_env(cls) -> "BoilerConfig":
        window_start = _parse_time(os.getenv("BOILER_WINDOW_START", "00:00"), "00:00")
        window_end = _parse_time(os.getenv("BOILER_WINDOW_END", "06:00"), "06:00")
        return cls(
            enabled=os.getenv("BOILER_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
            username=os.getenv("BOILER_TAPO_EMAIL") or os.getenv("TAPO_USERNAME"),
            password=os.getenv("BOILER_TAPO_PASSWORD") or os.getenv("TAPO_PASSWORD"),
            ip_address=os.getenv("BOILER_TAPO_IP"),
            window_start=window_start,
            window_end=window_end,
            total_run_sec=max(int(os.getenv("BOILER_TOTAL_RUN_SEC", "7200")), 0),
            poll_sec=max(int(os.getenv("BOILER_POLL_SEC", "300")), 1),
            active_w_threshold=float(os.getenv("BOILER_ACTIVE_W_THRESHOLD", "0")),
            state_file=os.getenv("BOILER_STATE_FILE", "logs/boiler_logs/boiler_state.json"),
            log_file=os.getenv("BOILER_LOG_FILE", "logs/boiler_logs/boiler.log"),
        )


class BoilerState:
    WAITING_WINDOW = "WaitingForWindow"
    WAITING_POWER = "WaitingForPower"
    RUNNING = "Running"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    EXPIRED = "Expired"


class BoilerScheduler:
    def __init__(self, tapo_service: TapoService, config: BoilerConfig | None = None, clock: Clock | None = None):
        self.config = config or BoilerConfig.from_env()
        self.clock = clock or Clock()
        self.tapo = tapo_service
        self.logger = self._setup_logger()

        self.current_date: Optional[str] = None
        self.remaining_sec: float = float(self.config.total_run_sec)
        self.state: str = BoilerState.WAITING_WINDOW
        self.last_update_monotonic: float = self.clock.monotonic()

        self._load_persisted_state()

    def _setup_logger(self):
        _ensure_dir(self.config.log_file)
        logger = logging.getLogger("boiler_scheduler")
        if not logger.handlers:
            handler = logging.FileHandler(self.config.log_file)
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        return logger

    def _window_bounds(self, ref: datetime) -> Tuple[datetime, datetime]:
        start_dt = datetime.combine(ref.date(), self.config.window_start)
        end_dt = datetime.combine(ref.date(), self.config.window_end)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        return start_dt, end_dt

    def _in_window(self, now: datetime) -> bool:
        start, end = self._window_bounds(now)
        return start <= now < end

    def _seconds_until_window(self, now: datetime) -> float:
        start, end = self._window_bounds(now)
        if now < start:
            return (start - now).total_seconds()
        if now >= end:
            next_start = start + timedelta(days=1)
            return (next_start - now).total_seconds()
        return 0

    def _reset_for_today(self, now: datetime):
        self.current_date = now.date().isoformat()
        self.remaining_sec = float(self.config.total_run_sec)
        self.state = BoilerState.WAITING_WINDOW
        self.last_update_monotonic = self.clock.monotonic()
        self._persist_state(now)
        self.logger.info("Boiler: Reset state for new day %s (remaining %.0fs)", self.current_date, self.remaining_sec)

    def _load_persisted_state(self):
        path = self.config.state_file
        try:
            if not os.path.exists(path):
                _ensure_dir(path)
                # no previous state; set below
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None

        now = self.clock.now()
        today = now.date().isoformat()
        start, end = self._window_bounds(now)
        if data and data.get("date") == today and start <= now < end:
            self.current_date = today
            self.remaining_sec = float(data.get("remaining_sec", self.config.total_run_sec))
            self.state = data.get("last_state", BoilerState.WAITING_POWER)
            self.logger.info("Boiler: Resuming persisted state %s remaining %.0fs", self.state, self.remaining_sec)
        else:
            self._reset_for_today(now)

    def _persist_state(self, now: datetime):
        state = {
            "date": self.current_date or now.date().isoformat(),
            "remaining_sec": round(self.remaining_sec, 2),
            "last_state": self.state,
            "last_update_ts": now.isoformat(),
        }
        _ensure_dir(self.config.state_file)
        try:
            with open(self.config.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f)
        except Exception:
            self.logger.warning("Boiler: Failed to persist state", exc_info=True)

    async def _ensure_off(self):
        try:
            await self.tapo.initialize()
            await self.tapo.turn_off()
            self.logger.info("Boiler: Turned socket OFF")
        except Exception:
            self.logger.warning("Boiler: Failed to turn off socket", exc_info=True)

    async def _is_online(self) -> bool:
        try:
            await self.tapo.initialize()
            await self.tapo.get_state()
            return True
        except Exception:
            return False

    async def _is_active(self) -> bool:
        """Return True when we should count time toward the quota."""
        if self.config.active_w_threshold <= 0:
            # If threshold is zero, count whenever the socket is on/online.
            return True
        try:
            power = await self.tapo.get_current_power()
            return power is not None and float(power) >= self.config.active_w_threshold
        except Exception:
            return False

    async def _start_socket(self):
        try:
            await self.tapo.initialize()
            await self.tapo.turn_on()
            self.logger.info("Boiler: Turned socket ON")
        except Exception:
            self.logger.warning("Boiler: Failed to turn on socket", exc_info=True)
            raise

    async def _tick(self, now: datetime):
        start, end = self._window_bounds(now)
        in_window = start <= now < end

        # Date rollover handling
        if self.current_date != now.date().isoformat():
            self._reset_for_today(now)

        if not in_window:
            # Outside window: mark expired and ensure off.
            if self.state not in (BoilerState.EXPIRED, BoilerState.WAITING_WINDOW):
                self.logger.info("Boiler: Window ended, stopping socket.")
            await self._ensure_off()
            self.state = BoilerState.EXPIRED
            self._persist_state(now)
            return self._seconds_until_window(now)

        # Inside window
        if self.remaining_sec <= 0:
            if self.state != BoilerState.COMPLETED:
                self.logger.info("Boiler: Completed required runtime; turning off.")
                await self._ensure_off()
                self.state = BoilerState.COMPLETED
                self._persist_state(now)
            return min(self.config.poll_sec, (end - now).total_seconds())

        online = await self._is_online()
        now_mono = self.clock.monotonic()

        if not online:
            prev = self.state
            self.state = BoilerState.WAITING_POWER if prev == BoilerState.WAITING_WINDOW else BoilerState.PAUSED
            if prev != self.state:
                self.logger.info("Boiler: State transition %s -> %s (waiting for power)", prev, self.state)
            else:
                self.logger.info(
                    "Boiler: Still waiting for power/online socket; retry in %ss (remaining %.0fs)",
                    self.config.poll_sec,
                    self.remaining_sec,
                )
            self.last_update_monotonic = now_mono  # avoid counting offline time as runtime
            self._persist_state(now)
            return self.config.poll_sec

        # Ensure socket on
        try:
            self.logger.info("Boiler: Reconnecting socket before turn ON")
            await self._start_socket()
        except Exception:
            self.state = BoilerState.PAUSED
            self._persist_state(now)
            return self.config.poll_sec

        active = await self._is_active()
        elapsed = max(now_mono - self.last_update_monotonic, 0)
        self.last_update_monotonic = now_mono

        if active:
            self.remaining_sec = max(self.remaining_sec - elapsed, 0)
            next_state = BoilerState.RUNNING if self.remaining_sec > 0 else BoilerState.COMPLETED
        else:
            next_state = BoilerState.PAUSED

        if next_state != self.state:
            self.logger.info(
                "Boiler: State transition %s -> %s (remaining %.0fs)", self.state, next_state, self.remaining_sec
            )
        self.state = next_state
        if self.state == BoilerState.COMPLETED:
            await self._ensure_off()

        self._persist_state(now)

        if self.state == BoilerState.RUNNING and active:
            next_sleep = min(self.config.poll_sec, (end - now).total_seconds())
            self.logger.info(
                "Boiler: Running; remaining %.0fs, next check in %ss", self.remaining_sec, next_sleep
            )
            return next_sleep

        if not active:
            # Update last_update_monotonic so paused time doesn't count toward runtime
            self.last_update_monotonic = self.clock.monotonic()
        self.logger.info(
            "Boiler: Paused/completed; next check in %ss (remaining %.0fs)", self.config.poll_sec, self.remaining_sec
        )
        return self.config.poll_sec

    async def run(self):
        if not self.config.enabled:
            self.logger.info("Boiler: Scheduler disabled; skipping run loop.")
            return
        self.logger.info("Boiler: Scheduler starting.")
        while True:
            now = self.clock.now()
            try:
                sleep_for = await self._tick(now)
            except Exception:
                self.logger.warning("Boiler: Unexpected error in tick", exc_info=True)
                sleep_for = self.config.poll_sec
            await asyncio.sleep(max(sleep_for, 1))
