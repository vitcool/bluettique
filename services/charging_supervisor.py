from dataclasses import dataclass

from utils.env import bool_env as _bool_env, int_env as _int_env


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
    ac_retry_interval_sec: int
    ac_retry_max_attempts: int
    ac_zero_power_off_sec: int
    offline_confirm_failures: int = 1
    offline_confirm_sec: int = 120
    charge_skip_above_percent: int = 98
    charge_skip_when_unknown: bool = True
    battery_max_age_sec: int = 600
    battery_unknown_wait_sec: int = 20
    monitor_read_failures: int = 3
    monitor_read_fail_sec: int = 120

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
            ac_retry_interval_sec=_int_env("AC_RETRY_INTERVAL_SEC", 30),
            ac_retry_max_attempts=_int_env("AC_RETRY_MAX_ATTEMPTS", 10),
            ac_zero_power_off_sec=_int_env("AC_ZERO_POWER_OFF_SEC", 300),
            offline_confirm_failures=_int_env("OFFLINE_CONFIRM_FAILURES", 1),
            offline_confirm_sec=_int_env("OFFLINE_CONFIRM_SEC", 120),
            charge_skip_above_percent=_int_env("CHARGE_SKIP_ABOVE_PERCENT", 98),
            charge_skip_when_unknown=_bool_env("CHARGE_SKIP_WHEN_UNKNOWN", True),
            battery_max_age_sec=_int_env("BATTERY_MAX_AGE_SEC", 600),
            battery_unknown_wait_sec=_int_env("BATTERY_UNKNOWN_WAIT_SEC", 20),
            monitor_read_failures=_int_env("MONITOR_READ_FAILURES", 3),
            monitor_read_fail_sec=_int_env("MONITOR_READ_FAIL_SEC", 120),
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
