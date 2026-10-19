import asyncio

import pytest

from charging_state_handler import ChargingStateHandler
from services.charging_supervisor import ChargingConfig


class FakeTapoController:
    async def get_status(self):
        return None


class ScriptedTapoController:
    """Reports online/offline per refresh from a scripted sequence."""

    def __init__(self, online_sequence):
        self._sequence = list(online_sequence)
        self._online = True
        self.status = self

        self.power_script = []
        self.stop_calls = 0

    async def get_status(self):
        self._online = self._sequence.pop(0)

    async def stop_charging(self):
        self.stop_calls += 1

    async def initialize(self):
        pass

    async def get_current_power(self):
        value = self.power_script.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def get_status_snapshot(self):
        return {"online": self._online}


class FakeBluettiController:
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
        return {"ac_output_on": ac_on, "ac_output_power": 0, "total_battery_percent": self.battery_percent, "battery_updated_at": self.battery_updated_at}


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


async def _run_wait_polls(handler, count):
    from charging_state_handler import WaitPowerState

    for _ in range(count):
        await handler.state.handle(handler)
        if not isinstance(handler.state, WaitPowerState):
            break


_HANDLERS = []


@pytest.fixture(autouse=True)
def _cancel_recovery_tasks():
    yield
    for h in _HANDLERS:
        if h.offline_recovery_task and not h.offline_recovery_task.done():
            h.offline_recovery_task.cancel()
    _HANDLERS.clear()


def _make_wait_handler(online_sequence, battery_percent=None, **config):
    from charging_state_handler import WaitPowerState

    tapo = ScriptedTapoController(online_sequence)
    tapo.status = type("S", (), {"get_status": lambda self: tapo.get_status_snapshot()})()
    handler = ChargingStateHandler(
        tapo_controller=tapo,
        bluetti_controller=FakeBluettiController([True], battery_percent=battery_percent),
        config=make_config(check_interval_sec=0, stable_power_interval_sec=0, **config),
    )
    handler.first_launch = False
    handler.state = WaitPowerState()
    _HANDLERS.append(handler)
    return handler


@pytest.mark.asyncio
async def test_single_failed_poll_does_not_start_charging():
    from charging_state_handler import WaitPowerState

    handler = _make_wait_handler([False, True, True])
    await _run_wait_polls(handler, 3)

    assert isinstance(handler.state, WaitPowerState)
    assert handler.offline_seen_in_wait is False
    # AC keep-alive fires immediately on the first failed poll, once.
    assert handler.bluetti_controller.turn_ac_calls == ["ON"]


@pytest.mark.asyncio
async def test_consecutive_failures_confirm_disconnect_then_start_charging():
    from charging_state_handler import StartChargingState

    handler = _make_wait_handler([False, False, False, True], battery_percent=50, offline_confirm_failures=3)
    await _run_wait_polls(handler, 4)

    assert isinstance(handler.state, StartChargingState)
    assert handler.bluetti_controller.turn_ac_calls == ["ON"]  # sent once, not per failed poll


@pytest.mark.asyncio
async def test_outage_duration_confirms_disconnect_before_failure_count():
    handler = _make_wait_handler([False, False], offline_confirm_failures=10, offline_confirm_sec=0)
    await _run_wait_polls(handler, 2)

    assert handler.offline_seen_in_wait is True


@pytest.mark.asyncio
async def test_failure_streak_resets_when_plug_comes_back():
    handler = _make_wait_handler([False, False, True, False, False, True], offline_confirm_failures=3)
    await _run_wait_polls(handler, 6)

    assert handler.offline_seen_in_wait is False
    assert handler.offline_failures == 0


@pytest.mark.asyncio
async def test_full_battery_skips_start_and_turns_socket_off():
    from charging_state_handler import WaitPowerState

    handler = _make_wait_handler([False, True], battery_percent=100, offline_confirm_failures=1)
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, WaitPowerState)
    assert handler.tapo_controller.stop_calls == 1
    assert handler.offline_seen_in_wait is False


@pytest.mark.asyncio
async def test_low_battery_starts_charging_immediately_on_return():
    from charging_state_handler import StartChargingState

    handler = _make_wait_handler([False, True], battery_percent=60, offline_confirm_failures=1)
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, StartChargingState)
    assert handler.tapo_controller.stop_calls == 0


@pytest.mark.asyncio
async def test_unknown_battery_blocks_start_and_turns_socket_off():
    from charging_state_handler import WaitPowerState

    handler = _make_wait_handler([False, True], battery_percent=None, offline_confirm_failures=1)
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, WaitPowerState)
    assert handler.tapo_controller.stop_calls == 1


@pytest.mark.asyncio
async def test_unknown_battery_can_be_allowed_by_config():
    from charging_state_handler import StartChargingState

    handler = _make_wait_handler(
        [False, True], battery_percent=None, offline_confirm_failures=1, charge_skip_when_unknown=False
    )
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, StartChargingState)


@pytest.mark.asyncio
async def test_stale_battery_reading_is_treated_as_unknown():
    import time
    from charging_state_handler import WaitPowerState

    handler = _make_wait_handler([False, True], battery_percent=50, offline_confirm_failures=1, battery_max_age_sec=600)
    handler.bluetti_controller.battery_updated_at = time.monotonic() - 3600
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, WaitPowerState)


@pytest.mark.asyncio
async def test_battery_level_arriving_within_wait_window_is_used():
    from charging_state_handler import StartChargingState

    handler = _make_wait_handler(
        [False, True], battery_percent=None, offline_confirm_failures=1, battery_unknown_wait_sec=5
    )
    original = handler.bluetti_controller.get_status
    calls = {"n": 0}

    def delayed_status():
        calls["n"] += 1
        if calls["n"] >= 3:
            handler.bluetti_controller.battery_percent = 40
        return original()

    handler.bluetti_controller.get_status = delayed_status
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, StartChargingState)


def _make_monitor_handler(power_script, **config):
    import time
    from charging_state_handler import MonitorChargingState

    handler = _make_wait_handler([], battery_percent=50, **config)
    handler.tapo_controller.power_script = list(power_script)
    handler.state = MonitorChargingState()
    handler.socket_on_at = time.monotonic() - 10_000  # past startup grace
    handler.first_power_check_at = None
    return handler


@pytest.mark.asyncio
async def test_monitor_tolerates_failed_reads_below_limit():
    from charging_state_handler import MonitorChargingState

    err = RuntimeError("boom")
    # each failed pass consumes two reads: the first attempt and the retry
    handler = _make_monitor_handler([err, err], monitor_read_failures=3)
    await handler.state.handle(handler)

    assert isinstance(handler.state, MonitorChargingState)
    assert handler.monitor_read_failures == 1
    assert handler.bluetti_controller.turn_ac_calls == ["ON"]
    assert handler.tapo_controller.stop_calls == 0


@pytest.mark.asyncio
async def test_monitor_recovers_and_releases_ac_keep_alive():
    from charging_state_handler import MonitorChargingState

    err = RuntimeError("boom")
    handler = _make_monitor_handler([err, err, 500.0], monitor_read_failures=3)
    await handler.state.handle(handler)
    await handler.state.handle(handler)

    assert isinstance(handler.state, MonitorChargingState)
    assert handler.monitor_read_failures == 0
    assert handler.bluetti_controller.turn_ac_calls == ["ON", "OFF"]


@pytest.mark.asyncio
async def test_monitor_falls_back_to_wait_after_limit_with_outage_confirmed():
    from charging_state_handler import WaitPowerState

    err = RuntimeError("boom")
    handler = _make_monitor_handler([err] * 4, monitor_read_failures=2)
    await handler.state.handle(handler)
    await handler.state.handle(handler)

    assert isinstance(handler.state, WaitPowerState)
    assert handler.offline_seen_in_wait is True
