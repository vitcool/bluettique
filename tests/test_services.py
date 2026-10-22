import asyncio
from types import SimpleNamespace

import pytest

from services.bluettiMqtt import BluettiMQTTService
from services.runtime_status import RuntimeStatusStore
from services.tapo import TapoService


def make_message(topic, payload):
    return SimpleNamespace(topic=topic, payload=payload.encode())


@pytest.fixture
def bluetti(monkeypatch):
    monkeypatch.setenv("BLUETTI_DEVICE_NAME", "AC180")
    return BluettiMQTTService()


def test_on_message_updates_status_values(bluetti):
    bluetti.on_message(None, None, make_message("bluetti/state/AC180/total_battery_percent", "87"))
    bluetti.on_message(None, None, make_message("bluetti/state/AC180/ac_output_on", "ON"))
    bluetti.on_message(None, None, make_message("bluetti/state/AC180/dc_output_on", "OFF"))
    bluetti.on_message(None, None, make_message("bluetti/state/AC180/ac_output_power", "35"))
    bluetti.on_message(None, None, make_message("bluetti/state/AC180/ac_input_power", "12.5"))

    status = bluetti.status.get_status()
    assert status["total_battery_percent"] == 87
    assert status["battery_updated_at"] is not None
    assert status["ac_output_on"] is True
    assert status["dc_output_on"] is False
    assert status["ac_output_power"] == 35
    assert status["ac_input_power"] == 12.5
    assert bluetti.device_connected is True


def test_on_message_parses_pack_details(bluetti):
    bluetti.on_message(None, None, make_message("bluetti/state/AC180/pack_details2", '{"percent": 55, "voltage": 51.2}'))
    bluetti.on_message(None, None, make_message("bluetti/state/AC180/pack_details3", "40"))

    status = bluetti.status.get_status()
    assert status["pack_details2_percent"] == 55.0
    assert status["pack_details2_voltage"] == 51.2
    assert status["pack_details3_percent"] == 40.0
    assert status["pack_details3_voltage"] is None


def test_on_message_ignores_other_devices(bluetti):
    bluetti.on_message(None, None, make_message("bluetti/state/OTHER/total_battery_percent", "10"))

    assert bluetti.status.get_status()["total_battery_percent"] is None
    assert bluetti.device_connected is False


def test_on_message_detects_device_name(monkeypatch):
    monkeypatch.delenv("BLUETTI_DEVICE_NAME", raising=False)
    service = BluettiMQTTService()
    service.on_message(None, None, make_message("bluetti/state/EB3A/total_battery_percent", "10"))

    assert service.device_name == "EB3A"


class FakePlug:
    def __init__(self, raw):
        self.raw = raw

    async def get_current_power(self):
        return self.raw


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        (12, 12.0),
        (SimpleNamespace(current_power=7.5), 7.5),
        (SimpleNamespace(current_power="bad"), None),
        ({"current_power": 3}, 3.0),
        ("4.5", 4.5),
        ("bad", None),
    ],
)
async def test_tapo_current_power_unwraps_sdk_result(raw, expected):
    service = TapoService(username="u", password="p", ip_address="1.2.3.4")
    service.device = FakePlug(raw)

    assert await service.get_current_power() == expected


def test_runtime_status_records_transition_and_bluetti_summary():
    store = RuntimeStatusStore()
    store.set_charging_transition("WAIT_POWER", "START_CHARGING", "why")
    store.update_bluetti({"ac_output_on": True, "total_battery_percent": 80})

    snapshot = store.snapshot()
    assert snapshot["charging_state"]["current_state"] == "START_CHARGING"
    assert snapshot["charging_state"]["last_transition"]["reason"] == "why"
    assert snapshot["power_summary"]["batteryPercent"] == 80
    assert snapshot["power_summary"]["acOutputOn"] is True
    assert snapshot["connection"]["last_message_ts"]


def test_failure_streak_confirms_on_count_or_duration():
    from services.failure_streak import FailureStreak

    by_count = FailureStreak(max_failures=2, max_sec=1000)
    assert by_count.register() is False
    assert by_count.register() is True
    by_count.reset()
    assert by_count.count == 0 and by_count.register() is False

    by_time = FailureStreak(max_failures=100, max_sec=0)
    assert by_time.register() is True


@pytest.mark.asyncio
async def test_power_off_until_confirmed_retries_until_telemetry_stops(monkeypatch):
    import time

    from controllers.bluetti import BluettiController

    controller = BluettiController()
    controller.connection_set = True
    controller.bluetti.device_connected = True
    sent = []
    controller.bluetti.power_off = lambda: sent.append(time.monotonic())
    monkeypatch.setattr(controller, "power_off", lambda: sent.append("teardown"))

    async def fast_sleep(_):
        # Telemetry keeps flowing for the first command, stops after the second.
        if len([s for s in sent if s != "teardown"]) < 2:
            controller.bluetti.status.battery_updated_at = time.monotonic()
        await real_sleep(0)

    real_sleep = asyncio.sleep
    monkeypatch.setattr("controllers.bluetti.asyncio.sleep", fast_sleep)

    assert await controller.power_off_until_confirmed(max_attempts=3, quiet_sec=0.01) is True
    assert len(sent) == 3 and sent[-1] == "teardown"


@pytest.mark.asyncio
async def test_power_off_until_confirmed_gives_up(monkeypatch):
    import time

    from controllers.bluetti import BluettiController

    controller = BluettiController()
    controller.connection_set = True
    controller.bluetti.device_connected = True
    sent = []
    controller.bluetti.power_off = lambda: sent.append(1)
    real_sleep = asyncio.sleep

    async def fast_sleep(_):
        controller.bluetti.status.battery_updated_at = time.monotonic()
        await real_sleep(0)

    monkeypatch.setattr("controllers.bluetti.asyncio.sleep", fast_sleep)

    assert await controller.power_off_until_confirmed(max_attempts=2, quiet_sec=0.01) is False
    assert len(sent) == 2
