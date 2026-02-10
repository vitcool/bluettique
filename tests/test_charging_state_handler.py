import asyncio

import pytest

from charging_state_handler import ChargingStateHandler
from services.charging_supervisor import ChargingConfig


class FakeTapoController:
    async def get_status(self):
        return None


class FakeBluettiController:
    def __init__(self, ac_status_sequence):
        self._sequence = list(ac_status_sequence)
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
        return {"ac_output_on": ac_on, "ac_output_power": 0}


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
    )
    defaults.update(overrides)
    return ChargingConfig(**defaults)


@pytest.mark.asyncio
async def test_offline_recovery_retries_ac_on_until_retry_limit():
    handler = ChargingStateHandler(
        tapo_controller=FakeTapoController(),
        bluetti_controller=FakeBluettiController([False]),
        config=make_config(ac_retry_max_attempts=3),
    )
    handler.offline_seen_in_wait = True

    handler.schedule_offline_recovery_check()
    await asyncio.sleep(0.45)
    handler.offline_recovery_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handler.offline_recovery_task

    assert handler.bluetti_controller.turn_ac_calls == ["ON", "ON", "ON"]
    assert handler.bluetti_controller.initialize_calls == 3


@pytest.mark.asyncio
async def test_offline_recovery_stops_retry_after_ac_turns_on():
    handler = ChargingStateHandler(
        tapo_controller=FakeTapoController(),
        bluetti_controller=FakeBluettiController([False, False, True, True, True]),
        config=make_config(ac_retry_max_attempts=10),
    )
    handler.offline_seen_in_wait = True

    handler.schedule_offline_recovery_check()
    await asyncio.sleep(0.45)
    calls_after_on = len(handler.bluetti_controller.turn_ac_calls)
    await asyncio.sleep(0.2)
    handler.offline_recovery_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handler.offline_recovery_task

    assert calls_after_on >= 1
    assert len(handler.bluetti_controller.turn_ac_calls) == calls_after_on
