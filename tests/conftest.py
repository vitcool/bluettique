import pytest

from charging_state_handler import ChargingStateHandler, WaitPowerState
from tests.fakes import FakeBluetti, FakeTapo, make_config


@pytest.fixture
def make_handler():
    """Build a handler in WAIT_POWER with fakes; recovery tasks are cancelled on teardown."""
    handlers = []

    def factory(online_sequence=(), battery_percent=None, ac_sequence=(True,), **config):
        settings = dict(check_interval_sec=0, stable_power_interval_sec=0)
        settings.update(config)
        handler = ChargingStateHandler(
            tapo_controller=FakeTapo(online_sequence),
            bluetti_controller=FakeBluetti(ac_sequence, battery_percent=battery_percent),
            config=make_config(**settings),
        )
        handler.first_launch = False
        handler.state = WaitPowerState()
        handlers.append(handler)
        return handler

    yield factory
    for handler in handlers:
        if handler.offline_recovery_task and not handler.offline_recovery_task.done():
            handler.offline_recovery_task.cancel()
