from pathlib import Path

from logs.webapp import server
from services.runtime_status import runtime_status_store


def test_api_status_uses_runtime_memory():
    runtime_status_store.reset()
    runtime_status_store.set_connection_meta("window_min", 7)
    runtime_status_store.set_charging_transition(
        "WAIT_POWER",
        "START_CHARGING",
        "offline->online",
        "2026-02-08T13:00:00+00:00",
    )
    runtime_status_store.set_boiler(
        {
            "date": "2026-02-08",
            "remaining_sec": 120.0,
            "last_state": "Running",
            "last_update_ts": "2026-02-08T13:00:00+00:00",
            "completed": False,
            "window_start": "00:00",
            "window_end": "06:00",
            "total_run_sec": 7200,
        }
    )
    runtime_status_store.update_bluetti(
        {
            "total_battery_percent": 65,
            "pack_details2_percent": 44,
            "pack_details3_percent": 0,
            "ac_output_on": True,
            "dc_output_on": False,
            "ac_output_power": 180,
            "dc_output_power": 0,
            "ac_input_power": 0.0,
            "dc_input_power": 0.0,
            "info_received": True,
        }
    )

    with server.app.test_client() as client:
        response = client.get("/api/status")
        assert response.status_code == 200
        payload = response.get_json()

    assert payload["ok"] is True
    assert payload["charging_state"]["current_state"] == "START_CHARGING"
    assert payload["boiler"]["last_state"] == "Running"
    assert payload["connection"]["window_min"] == 7
    assert payload["power_summary"]["batteryPercent"] == 65
    assert payload["power_summary"]["pack2Battery"] == 44
    assert payload["power_summary"]["pack3Battery"] == 0


def test_api_logs_combines_sources(monkeypatch, tmp_path):
    charging = tmp_path / "log.txt"
    boiler = tmp_path / "boiler.log"
    charging.write_text("c1\nc2\n", encoding="utf-8")
    boiler.write_text("b1\nb2\n", encoding="utf-8")

    monkeypatch.setattr(
        server,
        "LOG_SOURCES",
        [("charging", Path(charging)), ("boiler", Path(boiler))],
    )

    with server.app.test_client() as client:
        response = client.get("/api/logs?limit=10")
        assert response.status_code == 200
        payload = response.get_json()

    assert payload["ok"] is True
    assert payload["source_count"] == 2
    assert payload["sources"][0]["label"] == "charging"
    assert payload["sources"][0]["file"] == "log.txt"
    assert payload["sources"][0]["lines"] == ["c1", "c2"]
    assert payload["sources"][1]["label"] == "boiler"
    assert payload["sources"][1]["file"] == "boiler.log"
    assert payload["sources"][1]["lines"] == ["b1", "b2"]


def test_api_logs_returns_404_if_missing(monkeypatch, tmp_path):
    missing = tmp_path / "missing.log"
    monkeypatch.setattr(server, "LOG_SOURCES", [("charging", Path(missing))])

    with server.app.test_client() as client:
        response = client.get("/api/logs?limit=10")
        assert response.status_code == 404
        payload = response.get_json()

    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_log_files"


def test_api_logs_can_filter_by_source(monkeypatch, tmp_path):
    charging = tmp_path / "log.txt"
    boiler = tmp_path / "boiler.log"
    charging.write_text("c1\nc2\n", encoding="utf-8")
    boiler.write_text("b1\nb2\n", encoding="utf-8")

    monkeypatch.setattr(
        server,
        "LOG_SOURCES",
        [("charging", Path(charging)), ("boiler", Path(boiler))],
    )

    with server.app.test_client() as client:
        response = client.get("/api/logs?limit=10&source=boiler")
        assert response.status_code == 200
        payload = response.get_json()

    assert payload["ok"] is True
    assert payload["source_count"] == 1
    assert payload["sources"][0]["label"] == "boiler"
    assert payload["sources"][0]["lines"] == ["b1", "b2"]


def test_api_logs_rejects_unknown_source(monkeypatch, tmp_path):
    charging = tmp_path / "log.txt"
    charging.write_text("c1\n", encoding="utf-8")
    monkeypatch.setattr(server, "LOG_SOURCES", [("charging", Path(charging))])

    with server.app.test_client() as client:
        response = client.get("/api/logs?source=boiler")
        assert response.status_code == 400
        payload = response.get_json()

    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_log_source"


def test_api_status_includes_boiler_on_intervals(monkeypatch, tmp_path):
    runtime_status_store.reset()
    runtime_status_store.set_boiler(
        {
            "date": "2026-02-08",
            "remaining_sec": 0.0,
            "last_state": "Completed",
            "last_update_ts": "2026-02-08T02:00:00",
            "completed": True,
            "window_start": "00:00",
            "window_end": "06:00",
            "total_run_sec": 7200,
        }
    )

    boiler_log = tmp_path / "boiler.log"
    boiler_log.write_text(
        "\n".join(
            [
                "2026-02-08 00:10:00 | INFO | boiler_scheduler:1 | Boiler: Turned socket ON",
                "2026-02-08 00:40:00 | INFO | boiler_scheduler:1 | Boiler: Turned socket OFF",
                "2026-02-08 01:00:00 | INFO | boiler_scheduler:1 | Boiler: Turned socket ON",
                "2026-02-08 01:30:00 | INFO | boiler_scheduler:1 | Boiler: Turned socket OFF",
                "2026-02-09 00:05:00 | INFO | boiler_scheduler:1 | Boiler: Turned socket ON",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "BOILER_LOG_PATH", Path(boiler_log))

    with server.app.test_client() as client:
        response = client.get("/api/status")
        assert response.status_code == 200
        payload = response.get_json()

    assert payload["ok"] is True
    assert payload["boiler"]["on_intervals"] == [
        {"start": "2026-02-08 00:10:00", "end": "2026-02-08 00:40:00"},
        {"start": "2026-02-08 01:00:00", "end": "2026-02-08 01:30:00"},
    ]
