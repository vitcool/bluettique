import os
import asyncio
import logging
from tapo import ApiClient


class TapoService:
    def __init__(self, username: str | None = None, password: str | None = None, ip_address: str | None = None):
        # Allow per-device credentials while keeping defaults for the charging plug.
        self.tapo_username = username or os.getenv("TAPO_USERNAME")
        self.tapo_password = password or os.getenv("TAPO_PASSWORD")
        # Prefer a dedicated charging socket identifier if provided (e.g., IP)
        self.ip_address = ip_address or os.getenv("CHARGING_SOCKET_DEVICE_ID") or os.getenv("TAPO_IP_ADDRESS")
        self.device = None

    def reset_session(self):
        self.device = None

    async def initialize(self):
        # Always clear session and re-login to avoid stale/expired sessions.
        self.reset_session()
        logging.info("TAPO: Reconnecting to device %s", self.ip_address)
        try:
            await asyncio.wait_for(self._login(), timeout=20)
            logging.info("TAPO: Pairing successful")
        except Exception:
            logging.info("TAPO: Pairing failed")
            raise

    async def _login(self):
        try:
            client = ApiClient(self.tapo_username, self.tapo_password)
            self.device = await client.p110(self.ip_address)
        except Exception as e:
            logging.debug(f"TAPO: Login failed with error: {e}")
            raise

    async def turn_on(self):
        logging.info("TAPO: Turning device on...")
        try:
            await self.device.on()
        except Exception:
            # Session may be stale; reset and retry once
            self.reset_session()
            logging.debug("TAPO: turn_on failed; resetting session and retrying")
            await self.initialize()
            await self.device.on()

    async def turn_off(self):
        logging.info("TAPO: Turning device off...")
        try:
            await self.device.off()
        except Exception:
            self.reset_session()
            logging.debug("TAPO: turn_off failed; resetting session and retrying")
            await self.initialize()
            await self.device.off()

    async def get_state(self):
        try:
            return await self.device.get_device_info()
        except Exception:
            # Force re-login on next attempt after auth/network failures
            self.reset_session()
            logging.debug("TAPO: Failed to get state; session will be reset")
            raise

    async def get_current_power(self):
        logging.info("TAPO: Fetching current power usage...")
        raw_power = await self.device.get_current_power()
        # The SDK returns a CurrentPowerResult object; unwrap to the numeric value.
        if raw_power is None:
            return None
        if isinstance(raw_power, (int, float)):
            return float(raw_power)
        if hasattr(raw_power, "current_power"):
            try:
                return float(raw_power.current_power)
            except (TypeError, ValueError):
                return None
        if isinstance(raw_power, dict) and "current_power" in raw_power:
            try:
                return float(raw_power["current_power"])
            except (TypeError, ValueError):
                return None
        try:
            return float(raw_power)
        except (TypeError, ValueError):
            return None

    async def get_current_voltage(self):
        """Return the live socket voltage in volts when supported by the plug."""
        get_meter_data = getattr(self.device, "get_energy_meter_data", None)
        if get_meter_data is None:
            return None

        meter_data = await get_meter_data()
        if meter_data is None:
            return None
        if isinstance(meter_data, dict):
            values = meter_data
        elif hasattr(meter_data, "to_dict"):
            values = meter_data.to_dict()
        else:
            values = {}

        voltage = None
        for key in ("voltage", "voltage_v", "voltage_mv"):
            if key in values:
                voltage = values[key]
                if key == "voltage_mv":
                    try:
                        voltage = float(voltage) / 1000
                    except (TypeError, ValueError):
                        return None
                break
        if voltage is None:
            for key in ("voltage", "voltage_v", "voltage_mv"):
                if hasattr(meter_data, key):
                    voltage = getattr(meter_data, key)
                    if key == "voltage_mv":
                        try:
                            voltage = float(voltage) / 1000
                        except (TypeError, ValueError):
                            return None
                    break
        try:
            voltage = float(voltage)
        except (TypeError, ValueError):
            return None
        # Some firmware/API versions expose the raw millivolt value as voltage.
        if voltage > 1000:
            voltage /= 1000
        return voltage if 0 < voltage <= 1000 else None
