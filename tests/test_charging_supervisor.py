from services.charging_supervisor import ChargingSupervisor
from tests.fakes import make_config


def test_is_charging_respects_threshold():
    supervisor = ChargingSupervisor(make_config(charging_w_threshold=20))
    assert supervisor.is_charging(25) is True
    assert supervisor.is_charging(20) is True
    assert supervisor.is_charging(19.9) is False
