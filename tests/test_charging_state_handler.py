import asyncio
import time

import pytest

from charging_state_handler import MonitorChargingState, StartChargingState, WaitPowerState


@pytest.mark.asyncio
async def test_offline_recovery_retries_ac_on_until_retry_limit(make_handler):
    handler = make_handler(ac_sequence=[False], stable_power_interval_sec=0.05, ac_retry_max_attempts=3)
    handler.offline_seen_in_wait = True

    handler.schedule_offline_recovery_check()
    await asyncio.sleep(0.45)
    handler.offline_recovery_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handler.offline_recovery_task

    assert handler.bluetti_controller.turn_ac_calls == ["ON", "ON", "ON"]
    assert handler.bluetti_controller.initialize_calls == 3


@pytest.mark.asyncio
async def test_offline_recovery_stops_retry_after_ac_turns_on(make_handler):
    handler = make_handler(
        ac_sequence=[False, False, True, True, True], stable_power_interval_sec=0.05, ac_retry_max_attempts=10
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
    for _ in range(count):
        await handler.state.handle(handler)
        if not isinstance(handler.state, WaitPowerState):
            break


@pytest.mark.asyncio
async def test_single_failed_poll_does_not_start_charging(make_handler):
    handler = make_handler([False, True, True])
    await _run_wait_polls(handler, 3)

    assert isinstance(handler.state, WaitPowerState)
    assert handler.offline_seen_in_wait is False
    # AC keep-alive fires immediately on the first failed poll, once.
    assert handler.bluetti_controller.turn_ac_calls == ["ON"]


@pytest.mark.asyncio
async def test_consecutive_failures_confirm_disconnect_then_start_charging(make_handler):
    handler = make_handler([False, False, False, True], battery_percent=50, offline_confirm_failures=3)
    await _run_wait_polls(handler, 4)

    assert isinstance(handler.state, StartChargingState)
    assert handler.bluetti_controller.turn_ac_calls == ["ON"]  # sent once, not per failed poll


@pytest.mark.asyncio
async def test_outage_duration_confirms_disconnect_before_failure_count(make_handler):
    handler = make_handler([False, False], offline_confirm_failures=10, offline_confirm_sec=0)
    await _run_wait_polls(handler, 2)

    assert handler.offline_seen_in_wait is True


@pytest.mark.asyncio
async def test_failure_streak_resets_when_plug_comes_back(make_handler):
    handler = make_handler([False, False, True, False, False, True], offline_confirm_failures=3)
    await _run_wait_polls(handler, 6)

    assert handler.offline_seen_in_wait is False
    assert handler.offline_failures == 0


@pytest.mark.asyncio
async def test_full_battery_skips_start_and_turns_socket_off(make_handler):
    handler = make_handler([False, True], battery_percent=100, offline_confirm_failures=1)
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, WaitPowerState)
    assert handler.tapo_controller.stop_calls == 1
    assert handler.offline_seen_in_wait is False


@pytest.mark.asyncio
async def test_low_battery_starts_charging_immediately_on_return(make_handler):
    handler = make_handler([False, True], battery_percent=60, offline_confirm_failures=1)
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, StartChargingState)
    assert handler.tapo_controller.stop_calls == 0


@pytest.mark.asyncio
async def test_unknown_battery_blocks_start_and_turns_socket_off(make_handler):
    handler = make_handler([False, True], battery_percent=None, offline_confirm_failures=1)
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, WaitPowerState)
    assert handler.tapo_controller.stop_calls == 1


@pytest.mark.asyncio
async def test_unknown_battery_can_be_allowed_by_config(make_handler):
    handler = make_handler(
        [False, True], battery_percent=None, offline_confirm_failures=1, charge_skip_when_unknown=False
    )
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, StartChargingState)


@pytest.mark.asyncio
async def test_stale_battery_reading_is_treated_as_unknown(make_handler):
    handler = make_handler([False, True], battery_percent=50, offline_confirm_failures=1, battery_max_age_sec=600)
    handler.bluetti_controller.battery_updated_at = time.monotonic() - 3600
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, WaitPowerState)


@pytest.mark.asyncio
async def test_battery_level_arriving_within_wait_window_is_used(make_handler):
    handler = make_handler(
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


@pytest.fixture
def make_monitor_handler(make_handler):
    def factory(power_script, **config):
        handler = make_handler(battery_percent=50, **config)
        handler.tapo_controller.power_script = list(power_script)
        handler.state = MonitorChargingState()
        handler.socket_on_at = time.monotonic() - 10_000  # past startup grace
        handler.first_power_check_at = None
        return handler

    return factory


@pytest.mark.asyncio
async def test_monitor_tolerates_failed_reads_below_limit(make_monitor_handler):
    err = RuntimeError("boom")
    # each failed pass consumes two reads: the first attempt and the retry
    handler = make_monitor_handler([err, err], monitor_read_failures=3)
    await handler.state.handle(handler)

    assert isinstance(handler.state, MonitorChargingState)
    assert handler.monitor_read_failures == 1
    assert handler.bluetti_controller.turn_ac_calls == ["ON"]
    assert handler.tapo_controller.stop_calls == 0


@pytest.mark.asyncio
async def test_monitor_recovers_and_releases_ac_keep_alive(make_monitor_handler):
    err = RuntimeError("boom")
    handler = make_monitor_handler([err, err, 500.0], monitor_read_failures=3)
    await handler.state.handle(handler)
    await handler.state.handle(handler)

    assert isinstance(handler.state, MonitorChargingState)
    assert handler.monitor_read_failures == 0
    assert handler.bluetti_controller.turn_ac_calls == ["ON", "OFF"]


@pytest.mark.asyncio
async def test_monitor_falls_back_to_wait_after_limit_with_outage_confirmed(make_monitor_handler):
    err = RuntimeError("boom")
    handler = make_monitor_handler([err] * 4, monitor_read_failures=2)
    await handler.state.handle(handler)
    await handler.state.handle(handler)

    assert isinstance(handler.state, WaitPowerState)
    assert handler.offline_seen_in_wait is True


@pytest.mark.asyncio
async def test_battery_level_reported_during_slow_initialize_is_used(make_handler):
    handler = make_handler(
        [False, True], battery_percent=None, offline_confirm_failures=1, battery_unknown_wait_sec=1
    )
    bluetti = handler.bluetti_controller

    async def slow_initialize():
        await asyncio.sleep(1.2)  # longer than the wait window
        bluetti.battery_percent = 40

    bluetti.initialize = slow_initialize
    await _run_wait_polls(handler, 2)

    assert isinstance(handler.state, StartChargingState)
