from models.tapo import TapoStatus
from services.charging_supervisor import ChargingConfig


def make_config(**overrides) -> ChargingConfig:
    defaults = dict(
        charging_w_threshold=20,
        low_power_consecutive_count=3,
        check_interval_sec=900,
        first_power_check_delay_sec=30,
        startup_grace_sec=90,
        min_on_time_sec=1200,
        stable_power_checks=2,
        stable_power_interval_sec=0.05,
        recheck_cycle_enabled=True,
        recheck_off_sec=90,
        recheck_quick_checks=3,
        recheck_quick_interval_sec=20,
        ac_retry_interval_sec=0.1,
        ac_retry_max_attempts=3,
        ac_zero_power_off_sec=300,
        offline_confirm_failures=3,
        offline_confirm_sec=120,
        battery_unknown_wait_sec=0,
    )
    defaults.update(overrides)
    return ChargingConfig(**defaults)


class FakeTapo:
    """Tapo controller whose get_status() refresh plays back a scripted online/offline sequence."""

    def __init__(self, online_sequence=()):
        self._sequence = list(online_sequence)
        self.status = TapoStatus()
        self.power_script = []
        self.start_calls = 0
        self.stop_calls = 0
        self.initialize_calls = 0

    async def get_status(self):
        self.status.set_online(self._sequence.pop(0))

    async def start_charging(self):
        self.start_calls += 1

    async def stop_charging(self):
        self.stop_calls += 1

    async def initialize(self):
        self.initialize_calls += 1

    async def get_current_power(self):
        value = self.power_script.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeBluetti:
    def __init__(self, ac_status_sequence, battery_percent=None):
        self._sequence = list(ac_status_sequence)
        self.battery_percent = battery_percent
        self.battery_updated_at = None
        self._idx = 0
        self.turn_ac_calls = []
        self.initialize_calls = 0

    async def initialize(self):
        self.initialize_calls += 1

    def turn_ac(self, state: str):
        self.turn_ac_calls.append(state)

    def get_status(self):
        if self._idx < len(self._sequence):
            ac_on = self._sequence[self._idx]
            self._idx += 1
        else:
            ac_on = self._sequence[-1]
        return {
            "ac_output_on": ac_on,
            "ac_output_power": 0,
            "total_battery_percent": self.battery_percent,
            "battery_updated_at": self.battery_updated_at,
        }
