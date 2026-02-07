from services.charging_supervisor import ChargingSupervisor, ChargingConfig


def make_config(**overrides) -> ChargingConfig:
    defaults = dict(
        charging_w_threshold=20,
        low_power_consecutive_count=3,
        check_interval_sec=900,
        startup_grace_sec=90,
        min_on_time_sec=1200,
        stable_power_checks=2,
        stable_power_interval_sec=60,
        recheck_cycle_enabled=True,
        recheck_off_sec=90,
        recheck_quick_checks=3,
        recheck_quick_interval_sec=20,
    )
    defaults.update(overrides)
    return ChargingConfig(**defaults)


def test_is_charging_respects_threshold():
    supervisor = ChargingSupervisor(make_config(charging_w_threshold=20))
    assert supervisor.is_charging(25) is True
    assert supervisor.is_charging(20) is True
    assert supervisor.is_charging(19.9) is False


def test_should_stop_requires_low_power_and_min_time():
    config = make_config(charging_w_threshold=20, low_power_consecutive_count=2, min_on_time_sec=100)
    supervisor = ChargingSupervisor(config)

    assert supervisor.should_stop(5, low_counter=2, min_on_elapsed=150) is True
    assert supervisor.should_stop(5, low_counter=1, min_on_elapsed=150) is False
    assert supervisor.should_stop(5, low_counter=2, min_on_elapsed=50) is False
    assert supervisor.should_stop(30, low_counter=3, min_on_elapsed=200) is False


def test_recheck_confirms_charging_with_any_high_reading():
    supervisor = ChargingSupervisor(make_config(charging_w_threshold=15))
    assert supervisor.recheck_confirms_charging([5, 8, 10]) is False
    assert supervisor.recheck_confirms_charging([5, 18, 8]) is True
