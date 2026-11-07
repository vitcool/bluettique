from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "power_off_after_charge": False,
    "bluetti_monitoring_enabled": None,
    "boiler_enabled": None,
}


def _env_bluetti_monitoring_enabled() -> bool:
    return os.getenv("BLUETTI_MONITORING_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "y", "on"
    }


def _env_boiler_enabled() -> bool:
    return os.getenv("BOILER_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "y", "on"
    }


class UserSettings:
    """Runtime toggles changed from the dashboard; persisted so they survive restarts."""

    def __init__(self, path: str | None = None):
        self._lock = threading.Lock()
        self._path = Path(path or os.getenv("SETTINGS_FILE", "logs/settings.json"))
        self._data: Dict[str, Any] = dict(DEFAULTS)
        self._load()

    def configure(self, path: str) -> None:
        """Point the store at another file (used by tests) and reload from it."""
        with self._lock:
            self._path = Path(path)
            self._data = dict(DEFAULTS)
            self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text())
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            logging.warning("Settings: could not read %s; using defaults", self._path, exc_info=True)
            return
        if isinstance(raw, dict):
            for key, default in DEFAULTS.items():
                value = raw.get(key)
                if (default is None and type(value) is bool) or (
                    default is not None and isinstance(value, type(default))
                ):
                    self._data[key] = value

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2))
        except OSError:
            logging.warning("Settings: could not write %s", self._path, exc_info=True)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            result = dict(self._data)
            if result["bluetti_monitoring_enabled"] is None:
                result["bluetti_monitoring_enabled"] = _env_bluetti_monitoring_enabled()
            if result["boiler_enabled"] is None:
                result["boiler_enabled"] = _env_boiler_enabled()
            return result

    @property
    def bluetti_monitoring_enabled(self) -> bool:
        with self._lock:
            value = self._data["bluetti_monitoring_enabled"]
            return _env_bluetti_monitoring_enabled() if value is None else bool(value)

    def set_bluetti_monitoring_enabled(self, value: bool) -> None:
        with self._lock:
            self._data["bluetti_monitoring_enabled"] = bool(value)
            self._save()

    @property
    def boiler_enabled(self) -> bool:
        with self._lock:
            value = self._data["boiler_enabled"]
            return _env_boiler_enabled() if value is None else bool(value)

    def set_boiler_enabled(self, value: bool) -> None:
        with self._lock:
            self._data["boiler_enabled"] = bool(value)
            self._save()

    @property
    def power_off_after_charge(self) -> bool:
        with self._lock:
            return bool(self._data["power_off_after_charge"])

    def set_power_off_after_charge(self, value: bool) -> None:
        with self._lock:
            self._data["power_off_after_charge"] = bool(value)
            self._save()


user_settings = UserSettings()
