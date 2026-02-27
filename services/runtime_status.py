from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any, Dict


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeStatusStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {}
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._data = {
                "generated_at": utc_now_iso(),
                "power_summary": {},
                "bluetti": {},
                "connection": {},
                "charging_state": {
                    "current_state": None,
                    "updated_at": None,
                    "last_transition": None,
                },
                "boiler": None,
            }

    def _touch(self) -> None:
        self._data["generated_at"] = utc_now_iso()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def update_bluetti(self, status: Dict[str, Any]) -> None:
        with self._lock:
            self._data["bluetti"] = dict(status)
            summary = self._data.setdefault("power_summary", {})
            ts = utc_now_iso()

            summary["acOutputOn"] = status.get("ac_output_on")
            summary["acOutputTs"] = ts
            summary["batteryPercent"] = status.get("total_battery_percent")
            summary["batteryTs"] = ts
            summary["pack2Battery"] = status.get("pack_details2_percent")
            summary["pack2Voltage"] = status.get("pack_details2_voltage")
            summary["pack2Ts"] = ts
            summary["pack3Battery"] = status.get("pack_details3_percent")
            summary["pack3Voltage"] = status.get("pack_details3_voltage")
            summary["pack3Ts"] = ts
            summary["dcInputPower"] = status.get("dc_input_power")
            summary["dcInputTs"] = ts
            summary["acInputPower"] = status.get("ac_input_power")
            summary["acInputTs"] = ts
            summary["acOutputPower"] = status.get("ac_output_power")
            summary["acOutputPowerTs"] = ts

            connection = self._data.setdefault("connection", {})
            connection["last_message_ts"] = ts
            self._touch()

    def set_charging_state(self, state: str, timestamp: str | None = None) -> None:
        with self._lock:
            charging = self._data.setdefault("charging_state", {})
            charging["current_state"] = state
            charging["updated_at"] = timestamp or utc_now_iso()
            self._touch()

    def set_charging_transition(
        self,
        from_state: str,
        to_state: str,
        reason: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        with self._lock:
            ts = timestamp or utc_now_iso()
            charging = self._data.setdefault("charging_state", {})
            charging["current_state"] = to_state
            charging["updated_at"] = ts
            charging["last_transition"] = {
                "from": from_state,
                "to": to_state,
                "reason": reason,
                "timestamp": ts,
            }
            self._touch()

    def set_boiler(self, boiler_state: Dict[str, Any]) -> None:
        with self._lock:
            self._data["boiler"] = dict(boiler_state)
            self._touch()

    def set_connection_meta(self, key: str, value: Any) -> None:
        with self._lock:
            connection = self._data.setdefault("connection", {})
            connection[key] = value
            self._touch()


runtime_status_store = RuntimeStatusStore()
