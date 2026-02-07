import os
from dataclasses import dataclass
from typing import List


def _int_env(name: str, default: int) -> int:
    """Parse an int env var with a safe fallback."""
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class ChargingConfig:
    charging_w_threshold: int
    low_power_consecutive_count: int
    check_interval_sec: int
    first_power_check_delay_sec: int
    startup_grace_sec: int
    min_on_time_sec: int
    stable_power_checks: int
    stable_power_interval_sec: int
    recheck_cycle_enabled: bool
    recheck_off_sec: int
    recheck_quick_checks: int
    recheck_quick_interval_sec: int

    @classmethod
    def from_env(cls) -> "ChargingConfig":
        return cls(
            charging_w_threshold=_int_env("CHARGING_W_THRESHOLD", 20),
            low_power_consecutive_count=_int_env("LOW_POWER_CONSECUTIVE_COUNT", 3),
            check_interval_sec=_int_env("CHECK_INTERVAL_SEC", 900),
            first_power_check_delay_sec=_int_env("FIRST_POWER_CHECK_DELAY_SEC", 30),
            startup_grace_sec=_int_env("STARTUP_GRACE_SEC", 90),
            min_on_time_sec=_int_env("MIN_ON_TIME_SEC", 1200),
            stable_power_checks=_int_env("STABLE_POWER_CHECKS", 2),
            stable_power_interval_sec=_int_env("STABLE_POWER_INTERVAL_SEC", 60),
            recheck_cycle_enabled=_bool_env("RECHECK_CYCLE_ENABLED", True),
            recheck_off_sec=_int_env("RECHECK_OFF_SEC", 90),
            recheck_quick_checks=_int_env("RECHECK_QUICK_CHECKS", 3),
            recheck_quick_interval_sec=_int_env("RECHECK_QUICK_INTERVAL_SEC", 20),
        )


class ChargingSupervisor:
    def __init__(self, config: ChargingConfig | None = None):
        self.config = config or ChargingConfig.from_env()

    def is_charging(self, power_w: float | int | None) -> bool:
        """Return True when the measured power is above the threshold."""
        if power_w is None:
            return False
        try:
            return float(power_w) >= self.config.charging_w_threshold
        except (TypeError, ValueError):
            return False

    def should_stop(self, power_w: float | int | None, low_counter: int, min_on_elapsed: float) -> bool:
        """Decide whether a sustained low-power period justifies stopping."""
        return (
            low_counter >= self.config.low_power_consecutive_count
            and min_on_elapsed >= self.config.min_on_time_sec
            and not self.is_charging(power_w)
        )

    def recheck_confirms_charging(self, power_readings: List[float | int | None]) -> bool:
        """Return True if any quick recheck reading shows charging."""
        return any(self.is_charging(reading) for reading in power_readings)
