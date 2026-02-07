import json
from datetime import datetime, timedelta, time as dtime

import pytest

from services.boiler_scheduler import BoilerScheduler, BoilerConfig, Clock


class FakeClock(Clock):
    def __init__(self, now_dt: datetime, mono: float = 0.0):
        self._now = now_dt
        self._mono = mono

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float):
        self._mono += seconds
        self._now += timedelta(seconds=seconds)


class FakeTapo:
    def __init__(self, online=True, power=15.0):
        self.online = online
        self.power = power
        self.on_called = 0
        self.off_called = 0

    async def initialize(self):
        if not self.online:
            raise RuntimeError("offline")

    async def get_state(self):
        if not self.online:
            raise RuntimeError("offline")
        return {"device_on": True}

    async def turn_on(self):
        self.on_called += 1

    async def turn_off(self):
        self.off_called += 1

    async def get_current_power(self):
        if not self.online:
            raise RuntimeError("offline")
        return self.power


def make_config(tmp_path, **overrides) -> BoilerConfig:
    base = dict(
        enabled=True,
        username="u",
        password="p",
        ip_address="1.2.3.4",
        window_start=dtime(hour=0, minute=0),
        window_end=dtime(hour=6, minute=0),
        total_run_sec=1200,
        poll_sec=10,
        active_w_threshold=0,
        state_file=str(tmp_path / "state.json"),
        log_file=str(tmp_path / "boiler.log"),
    )
    base.update(overrides)
    return BoilerConfig(**base)


@pytest.mark.asyncio
async def test_resume_from_persisted_state(tmp_path):
    now = datetime(2026, 2, 1, 1, 0, 0)
    clock = FakeClock(now)
    persisted = {
        "date": now.date().isoformat(),
        "remaining_sec": 500,
        "last_state": "Paused",
        "last_update_ts": now.isoformat(),
    }
    state_file = tmp_path / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(persisted))

    config = make_config(tmp_path, state_file=str(state_file))
    scheduler = BoilerScheduler(FakeTapo(), config=config, clock=clock)

    assert scheduler.remaining_sec == 500
    assert scheduler.state == "Paused"


@pytest.mark.asyncio
async def test_reset_when_outside_window(tmp_path):
    now = datetime(2026, 2, 1, 12, 0, 0)
    clock = FakeClock(now)
    config = make_config(tmp_path)
    scheduler = BoilerScheduler(FakeTapo(), config=config, clock=clock)

    await scheduler._tick(clock.now())

    # Outside window -> expired and ensures next reset uses today's date
    assert scheduler.state == "Expired"
    assert scheduler.current_date == now.date().isoformat()


@pytest.mark.asyncio
async def test_counts_remaining_time_only_when_active(tmp_path):
    now = datetime(2026, 2, 1, 1, 0, 0)
    clock = FakeClock(now)
    tapo = FakeTapo(power=20.0)
    config = make_config(tmp_path, total_run_sec=1200, active_w_threshold=10)
    scheduler = BoilerScheduler(tapo, config=config, clock=clock)

    # First tick: inside window, online, active -> should be RUNNING
    await scheduler._tick(clock.now())
    assert scheduler.state == "Running"
    clock.advance(600)
    await scheduler._tick(clock.now())
    assert 550 <= scheduler.remaining_sec <= 650  # elapsed ~600s

    # Drop power below threshold -> pause, remaining should not decrease after next tick
    tapo.power = 0.0
    clock.advance(60)
    prev_remaining = scheduler.remaining_sec
    await scheduler._tick(clock.now())
    assert scheduler.state == "Paused"
    assert abs(scheduler.remaining_sec - prev_remaining) < 1
