# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Raspberry Pi service that automates a home energy setup: it charges an EV/device via a TP-Link Tapo P110 smart plug based on real-time power draw, manages a Bluetti power station's AC/DC outputs over MQTT/BLE, runs a nightly boiler scheduler against a second Tapo plug, and serves a small Flask dashboard for live status/logs. Runs as a single long-lived `asyncio` process, normally inside Docker on the Pi (needs host BLE/dbus access).

## Running

- Local: `source .venv/bin/activate` (or create one) then `pip install -r requirements.txt`, `python main.py`. Requires a `.env` (see `.env.example` / README for the full variable list).
- Docker (how it actually runs on the Pi): `docker compose up -d --build`. The compose file runs `--privileged`, host networking/PID namespace, and bind-mounts dbus/bluetooth so BlueZ on the host is reachable from the container. `mosquitto` (the local MQTT broker) and `python main.py` start together in the container entrypoint.
- Web dashboard: served on `WEBAPP_PORT` (default 8080) once `main.py` starts, unless `WEBAPP_ENABLED=false`.

## Tests

- `pytest` (config in `pytest.ini`: `pythonpath = .`, `asyncio_mode = auto`) — async tests use plain `@pytest.mark.asyncio` with no extra fixture setup needed.
- Run a single file: `pytest tests/test_charging_state_handler.py`; single test: `pytest tests/test_charging_state_handler.py::test_name`.
- Tests construct `ChargingConfig`/`BoilerConfig` dataclasses directly with explicit kwargs (see `make_config()` helpers in the test files) rather than going through env vars — follow that pattern for new tests, and inject fakes for `TapoService`/clock rather than hitting real devices.

## Architecture

**Two independent async loops share one process**, started from `main.py`:

1. **Charging state machine** (`charging_state_handler.py`) — the main loop, runs forever via `while True: await charging_handler.handle_state()`. It's a classic state pattern: each `ChargingState` subclass (`WaitPowerState → StartChargingState → MonitorChargingState → RecheckState/StopChargingState → ...`) implements `handle()` and calls `handler.set_state(...)` to transition. State is driven by Tapo power readings compared against thresholds in `ChargingConfig`/`ChargingSupervisor` (`services/charging_supervisor.py`). While waiting for Tapo to come back online, it kicks off a background "offline recovery" task that nudges the Bluetti's AC output on/off to avoid wasting standby power — this logic lives inline in `ChargingStateHandler.schedule_offline_recovery_check`.
2. **Boiler scheduler** (`services/boiler_scheduler.py`) — an independent `asyncio.create_task`, only started if `BOILER_ENABLED=true`. Also a small state machine (`BoilerState`: WaitingForWindow/WaitingForPower/Running/Paused/Completed) that guarantees a total runtime quota within a nightly time window on a *separate* Tapo socket. Persists progress to a JSON state file (`BOILER_STATE_FILE`) so a restart mid-window resumes the remaining seconds instead of restarting the quota.

**Controller → Service → device SDK layering** (applies to both Bluetti and Tapo):
- `controllers/*.py` — orchestration-facing API used by the state machines (`BluettiController`, `TapoController`). Owns retry/reconnect policy and translates device state into the shapes the state machine expects.
- `services/*.py` — thin wrappers around the actual device protocol: `services/tapo.py` wraps the `tapo` PyPI SDK (`ApiClient().p110(...)`); `services/bluettiMqtt.py` shells out to the `bluetti-mqtt` CLI as a subprocess to bridge BLE→MQTT, then talks to it via `paho-mqtt` pub/sub (`bluetti/state/#` / `bluetti/command/<device>/...`).
- `models/*.py` — plain status containers (`BluettiStatus`, `TapoStatus`) with `update_status`/`get_status`/`reset`.

**Cross-cutting state sharing**: `services/runtime_status.py` holds a single in-memory, thread-safe `runtime_status_store` singleton. Both the MQTT message callback (background thread) and the charging/boiler loops push updates into it; the Flask webapp reads from it for `/api/status`. This is how the dashboard gets live data without polling the state machines directly.

**Webapp lives under `logs/webapp/`, not at the top level** — `logs/webapp/server.py` (Flask app imported in `main.py` as `from logs.webapp.server import run_web_server`, run in a background daemon thread) serves `index.html`/`app.js`/`style.css` as static files plus two JSON endpoints:
- `/api/status` — merges the live `runtime_status_store` snapshot with on-disk fallbacks (`boiler_state.json`) when live data isn't available yet.
- `/api/logs` — tails the rotating log files (`logs/log.txt` + `logs/boiler_logs/boiler.log`), supports `source`, `since`, `day` (`today`/`prev`), and `limit` query params. It parses two historical log line formats (`LOG_LINE_RE_NEW`/`LOG_LINE_RE_OLD`) and derives charging-state/boiler-interval history by regex-matching log lines when the in-memory store doesn't have it (e.g. after a restart).

**Config pattern**: almost every tunable lives in `.env` and is read through a `@dataclass` + `from_env()` classmethod (`ChargingConfig`, `BoilerConfig`) using small `_int_env`/`_bool_env` helpers with safe fallbacks — follow this pattern rather than scattering `os.getenv` calls through logic code.

**Logging**: `utils/logger.py` sets up a root logger with both a `TimedRotatingFileHandler` (`logs/log.txt`, rotates nightly, keeps 7 days) and a stream handler; level is `DEBUG` when `ENV=dev` else `INFO`. The boiler scheduler sets up its own separate non-propagating file logger (`logs/boiler_logs/boiler.log`) in `BoilerScheduler._setup_logger`. The webapp's log-tailing code depends on the exact log line format in `LOG_FORMAT` — if you change it, update the regexes in `logs/webapp/server.py` too.
