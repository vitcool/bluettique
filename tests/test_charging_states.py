import asyncio
import time

import pytest

from charging_state_handler import (
    MonitorChargingState,
    StartChargingState,
    StopChargingState,
    WaitPowerState,
)


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
async def test_monitor_without_timestamp_restarts_flow(make_handler):
    handler = make_handler()
    handler.state = MonitorChargingState()
    handler.socket_on_at = None
    await handler.state.handle(handler)

    assert isinstance(handler.state, StartChargingState)


@pytest.mark.asyncio
async def test_monitor_waits_for_first_power_check_without_reading(make_monitor_handler):
    handler = make_monitor_handler([500.0])
    handler.first_power_check_at = time.monotonic() + 1000
    await handler.state.handle(handler)

    assert isinstance(handler.state, MonitorChargingState)
    assert handler.tapo_controller.power_script == [500.0]
    assert handler.first_power_check_at is not None


@pytest.mark.asyncio
async def test_monitor_stops_after_stable_low_checks(make_monitor_handler):
    handler = make_monitor_handler([1.0, 1.0], stable_power_checks=2)
    await handler.state.handle(handler)
    assert isinstance(handler.state, MonitorChargingState)
    assert handler.stable_checks_remaining == 1

    await handler.state.handle(handler)
    assert isinstance(handler.state, StopChargingState)


@pytest.mark.asyncio
async def test_monitor_charging_reading_resets_stable_checks(make_monitor_handler):
    handler = make_monitor_handler([1.0, 500.0], stable_power_checks=2)
    await handler.state.handle(handler)
    await handler.state.handle(handler)

    assert isinstance(handler.state, MonitorChargingState)
    assert handler.stable_checks_remaining == 2


@pytest.mark.asyncio
async def test_monitor_charging_inside_startup_grace_keeps_monitoring(make_monitor_handler):
    handler = make_monitor_handler([500.0], startup_grace_sec=90)
    handler.socket_on_at = time.monotonic() - 10
    await handler.state.handle(handler)

    assert isinstance(handler.state, MonitorChargingState)


@pytest.mark.asyncio
async def test_monitor_keeps_monitoring_while_charging_after_grace(make_monitor_handler):
    handler = make_monitor_handler([500.0] * 5)
    for _ in range(5):
        await handler.state.handle(handler)

    assert isinstance(handler.state, MonitorChargingState)


@pytest.mark.asyncio
async def test_start_turns_socket_on_ac_off_and_monitors(make_handler):
    handler = make_handler(first_power_check_delay_sec=30)
    handler.state = StartChargingState()
    await handler.state.handle(handler)

    assert isinstance(handler.state, MonitorChargingState)
    assert handler.tapo_controller.start_calls == 1
    # the fake keeps reporting AC on, so the recovery loop may fire again; the first call is what matters
    assert handler.bluetti_controller.turn_ac_calls[0] == "OFF"
    assert handler.first_power_check_at == handler.socket_on_at + 30
    assert handler.stable_checks_remaining == handler.config.stable_power_checks


@pytest.mark.asyncio
async def test_start_failure_returns_to_wait(make_handler):
    handler = make_handler()
    handler.state = StartChargingState()

    async def boom():
        raise RuntimeError("boom")

    handler.tapo_controller.start_charging = boom
    await handler.state.handle(handler)

    assert isinstance(handler.state, WaitPowerState)


@pytest.mark.asyncio
async def test_stop_turns_socket_off_and_resets(make_handler):
    handler = make_handler()
    handler.state = StopChargingState()
    handler.socket_on_at = time.monotonic()
    handler.first_power_check_at = time.monotonic()
    await handler.state.handle(handler)

    assert isinstance(handler.state, WaitPowerState)
    assert handler.tapo_controller.stop_calls == 1
    assert handler.socket_on_at is None
    assert handler.first_power_check_at is None


@pytest.mark.asyncio
async def test_set_state_away_from_wait_cancels_recovery_task(make_handler):
    handler = make_handler(ac_sequence=[False], stable_power_interval_sec=0.05)
    handler.schedule_offline_recovery_check()
    task = handler.offline_recovery_task
    handler.set_state(StartChargingState(), "test")
    await asyncio.sleep(0)

    assert task.cancelled()
    assert handler.offline_recovery_task is None


@pytest.mark.asyncio
async def test_set_state_to_wait_resets_outage_tracking_but_keeps_task(make_handler):
    handler = make_handler(ac_sequence=[False], stable_power_interval_sec=0.05)
    handler.schedule_offline_recovery_check()
    task = handler.offline_recovery_task
    handler.offline_seen_in_wait = True
    handler.offline_streak.register()
    handler.ac_keep_alive_sent = True
    handler.set_state(WaitPowerState(), "test")

    assert handler.offline_seen_in_wait is False
    assert handler.offline_failures == 0
    assert handler.ac_keep_alive_sent is False
    assert handler.offline_recovery_task is task and not task.done()


@pytest.mark.asyncio
async def test_release_ac_keep_alive_turns_ac_off_once(make_handler):
    handler = make_handler(ac_sequence=[True])
    await handler.trigger_ac_keep_alive()
    await handler.trigger_ac_keep_alive()
    assert handler.bluetti_controller.turn_ac_calls == ["ON"]

    await handler.release_ac_keep_alive()
    await handler.release_ac_keep_alive()
    assert handler.bluetti_controller.turn_ac_calls == ["ON", "OFF"]
    assert handler.ac_keep_alive_sent is False
    assert handler.offline_recovery_task is None


@pytest.mark.asyncio
async def test_offline_recovery_turns_ac_off_after_zero_power(make_handler):
    handler = make_handler(ac_sequence=[True], stable_power_interval_sec=0.05, ac_zero_power_off_sec=0.1)
    handler.schedule_offline_recovery_check()
    await asyncio.sleep(0.4)

    # the fake keeps reporting AC on, so the recovery loop may fire again; the first call is what matters
    assert handler.bluetti_controller.turn_ac_calls[0] == "OFF"
