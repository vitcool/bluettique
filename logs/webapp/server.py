from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, request
from services.runtime_status import runtime_status_store

BASE_DIR = Path(__file__).resolve().parent
LOG_SOURCES = [
    ("charging", BASE_DIR / "../log.txt"),
    ("boiler", BASE_DIR / "../boiler_logs/boiler.log"),
]
STATUS_SOURCE_CANDIDATES = [
    BASE_DIR / "system_status.json",
    BASE_DIR / "../system_status.json",
]
BOILER_STATE_PATH = BASE_DIR / "../boiler_logs/boiler_state.json"
CHARGING_LOG_PATH = BASE_DIR / "../log.txt"
DEFAULT_LIMIT = 500
MAX_LIMIT = 5000
MAX_READ_BYTES = 2 * 1024 * 1024
STATE_SCAN_LINE_LIMIT = 4000

TRANSITION_RE = re.compile(
    r"Charging:\s+State transition\s+([A-Za-z0-9_]+)\s+->\s+([A-Za-z0-9_]+)(?:\s+\((.+)\))?"
)
STATE_LINE_RE = re.compile(r"Charging:\s+([A-Z_]+)\s+-")
LOG_LINE_RE_NEW = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\|\s+[A-Z]+\s+\|\s+[^|]+\|\s+(?P<msg>.*)$"
)
LOG_LINE_RE_OLD = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - [^-]+ - (?P<msg>.*)$"
)

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")


def parse_limit(raw_limit: str | None) -> int:
    if raw_limit is None:
        return DEFAULT_LIMIT
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def select_log_sources(raw_source: str | None) -> List[tuple[str, Path]]:
    if not raw_source:
        return LOG_SOURCES
    return [source for source in LOG_SOURCES if source[0] == raw_source]


def tail_lines(path: Path, limit: int) -> List[str]:
    if limit <= 0:
        return []

    block_size = 8192
    data = b""
    bytes_read = 0

    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        file_size = handle.tell()
        pos = file_size

        while pos > 0 and data.count(b"\n") <= limit and bytes_read < MAX_READ_BYTES:
            read_size = min(block_size, pos)
            pos -= read_size
            handle.seek(pos)
            chunk = handle.read(read_size)
            data = chunk + data
            bytes_read += read_size

    text = data.decode("utf-8", errors="replace")
    return text.splitlines()[-limit:]


def normalize_state_name(raw_name: str) -> str:
    if not raw_name:
        return raw_name
    if raw_name.endswith("State"):
        raw_name = raw_name[:-5]
    if raw_name.isupper() and "_" in raw_name:
        return raw_name
    return re.sub(r"(?<!^)(?=[A-Z])", "_", raw_name).upper()


def parse_log_line(line: str) -> tuple[str | None, str | None]:
    normalized = line.strip()
    for regex in (LOG_LINE_RE_NEW, LOG_LINE_RE_OLD):
        match = regex.match(normalized)
        if match:
            return match.group("ts"), match.group("msg")
    return None, None


def read_json_file(path: Path) -> Dict[str, Any] | None:
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_file():
        return None
    try:
        import json

        with resolved.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_status_base() -> Dict[str, Any]:
    for candidate in STATUS_SOURCE_CANDIDATES:
        data = read_json_file(candidate)
        if data is not None:
            return data
    return {}


def extract_charging_state() -> Dict[str, Any]:
    resolved = CHARGING_LOG_PATH.resolve()
    if not resolved.exists() or not resolved.is_file():
        return {
            "current_state": None,
            "updated_at": None,
            "last_transition": None,
        }

    lines = tail_lines(resolved, STATE_SCAN_LINE_LIMIT)
    current_state = None
    updated_at = None
    last_transition: Dict[str, Any] | None = None

    for line in lines:
        ts, msg = parse_log_line(line)
        if not msg:
            continue

        transition = TRANSITION_RE.search(msg)
        if transition:
            from_state = normalize_state_name(transition.group(1))
            to_state = normalize_state_name(transition.group(2))
            reason = transition.group(3) or None
            current_state = to_state
            updated_at = ts
            last_transition = {
                "from": from_state,
                "to": to_state,
                "reason": reason,
                "timestamp": ts,
            }
            continue

        state_line = STATE_LINE_RE.search(msg)
        if state_line:
            current_state = normalize_state_name(state_line.group(1))
            updated_at = ts

    return {
        "current_state": current_state,
        "updated_at": updated_at,
        "last_transition": last_transition,
    }


def extract_last_message_ts() -> str | None:
    resolved = CHARGING_LOG_PATH.resolve()
    if not resolved.exists() or not resolved.is_file():
        return None

    for line in reversed(tail_lines(resolved, STATE_SCAN_LINE_LIMIT)):
        ts, msg = parse_log_line(line)
        if msg and "Received message:" in msg:
            return ts
    return None


def build_status_payload() -> Dict[str, Any]:
    base_status = load_status_base()
    runtime_status = runtime_status_store.snapshot()
    status_payload: Dict[str, Any] = dict(base_status)

    runtime_power = runtime_status.get("power_summary")
    if isinstance(runtime_power, dict) and runtime_power:
        status_payload["power_summary"] = runtime_power
    else:
        status_payload.setdefault("power_summary", {})

    runtime_bluetti = runtime_status.get("bluetti")
    if isinstance(runtime_bluetti, dict) and runtime_bluetti:
        status_payload["bluetti"] = runtime_bluetti

    runtime_boiler = runtime_status.get("boiler")
    if isinstance(runtime_boiler, dict) and runtime_boiler:
        status_payload["boiler"] = runtime_boiler
    elif not status_payload.get("boiler"):
        boiler = read_json_file(BOILER_STATE_PATH)
        if boiler is not None:
            status_payload["boiler"] = boiler

    runtime_charging = runtime_status.get("charging_state")
    if (
        isinstance(runtime_charging, dict)
        and runtime_charging.get("current_state")
    ):
        status_payload["charging_state"] = runtime_charging
    else:
        status_payload["charging_state"] = extract_charging_state()

    connection = status_payload.get("connection")
    if not isinstance(connection, dict):
        connection = {}
    runtime_connection = runtime_status.get("connection")
    if isinstance(runtime_connection, dict):
        connection.update(runtime_connection)
    if not connection.get("last_message_ts"):
        last_message_ts = extract_last_message_ts()
        if last_message_ts:
            connection["last_message_ts"] = last_message_ts
    status_payload["connection"] = connection

    generated_at = runtime_status.get("generated_at") or status_payload.get("generated_at")
    if not generated_at:
        generated_at = datetime.now(timezone.utc).isoformat()
    status_payload["generated_at"] = generated_at

    return status_payload


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/logs")
def api_logs():
    limit = parse_limit(request.args.get("limit"))
    source = request.args.get("source")
    selected_sources = select_log_sources(source)
    if source and not selected_sources:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "code": "invalid_log_source",
                        "message": f"Unknown log source '{source}'.",
                        "available_sources": [label for label, _ in LOG_SOURCES],
                    },
                }
            ),
            400,
        )

    missing = []
    combined_lines: List[str] = []
    sources_payload: List[Dict[str, Any]] = []

    for label, source_path in selected_sources:
        resolved = source_path.resolve()
        if not resolved.exists() or not resolved.is_file():
            missing.append(str(source_path))
            continue

        lines = tail_lines(resolved, limit)
        sources_payload.append(
            {
                "label": label,
                "file": source_path.name,
                "line_count": len(lines),
                "lines": lines,
            }
        )
        combined_lines.extend(lines)

    if not sources_payload:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "code": "missing_log_files",
                        "message": "No log files are available.",
                        "files": missing,
                    },
                }
            ),
            404,
        )

    return jsonify(
        {
            "ok": True,
            "limit": limit,
            "source_count": len(sources_payload),
            "missing_files": missing,
            "sources": sources_payload,
            "logs": "\n".join(combined_lines),
        }
    )


@app.get("/api/status")
def api_status():
    status_payload = build_status_payload()
    return jsonify({"ok": True, **status_payload})


def run_web_server(host: str = "0.0.0.0", port: int = 8080):
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run_web_server()
