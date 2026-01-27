import asyncio
import os
import subprocess
import logging
import shutil
import threading
from models.bluetti import BluettiStatus
import paho.mqtt.client as mqtt


class BluettiMQTTService:
    def __init__(self):
        self.broker_host = os.getenv("BLUETTI_BROKER_HOST", "localhost")
        self.mac_address = os.getenv("BLUETTI_MAC_ADDRESS")
        self.device_name = os.getenv("BLUETTI_DEVICE_NAME")
        self.broker_interval = os.getenv("BLUETTI_BROKER_INTERVAL", "30")
        self.broker_connection_timeout = max(
            int(os.getenv("BLUETTI_BROKER_CONNECTION_TIMEOUT", "90")), 90
        )
        # Retries for pairing the first time; keeps runs resilient to flaky BT.
        self.connect_retries = max(int(os.getenv("BLUETTI_BROKER_RETRIES", "3")), 1)
        self.connect_retry_delay = max(int(os.getenv("BLUETTI_BROKER_RETRY_DELAY", "5")), 1)
        self.broker_adapter = os.getenv("BLUETTI_BROKER_ADAPTER")
        self.client = mqtt.Client()

        # Subscribe to necessary topics
        # Subscribe to all devices so we still see updates if the configured
        # device name is wrong/missing; we filter in on_message.
        self.subscribe_topic = "bluetti/state/#"

        self.device_connected = False
        self.status = BluettiStatus()

    async def connect(self):
        if not self._validate_config():
            return False
        self._log_config()
        for attempt in range(1, self.connect_retries + 1):
            try:
                if self.device_connected:
                    self.device_connected = False
                if not self.start_broker():
                    logging.error("Failed to start broker; aborting connect attempt.")
                    return False
                self.client.on_connect = self.on_connect
                self.client.on_message = self.on_message
                try:
                    self.client.connect(self.broker_host, 1883, keepalive=60)
                except Exception as e:
                    logging.error(f"MQTT connection failed: {e}")
                self.start_client()
                try:
                    await asyncio.wait_for(
                        self._wait_for_pairing(), timeout=self.broker_connection_timeout
                    )
                    return True
                except asyncio.TimeoutError:
                    logging.warning(
                        "Timed out waiting for Bluetti pairing; stopping client and broker."
                    )
                    self.stop_client()
                    self.stop_broker()
            except Exception as e:
                logging.debug(f"Exception occurred during connection attempt {attempt}: {e}")
                self.stop_client()
                self.stop_broker()

            if attempt < self.connect_retries:
                logging.info(
                    f"Retrying Bluetti connection in {self.connect_retry_delay}s "
                    f"(attempt {attempt}/{self.connect_retries} failed)..."
                )
                await asyncio.sleep(self.connect_retry_delay)

        logging.error(
            f"All {self.connect_retries} Bluetti connection attempts failed; giving up."
        )
        return False

    async def _wait_for_pairing(self):
        while not self.device_connected:
            await asyncio.sleep(0.1)

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logging.debug(f"MQTT connected to {self.broker_host}; subscribing to {self.subscribe_topic}")
            client.subscribe(self.subscribe_topic)
            logging.debug(f"CONNECTED to {self.broker_host}")
        else:
            logging.debug(f"Failed to connect, return code {rc}")

    def on_message(self, client, userdata, message):
        logging.info(f"Received message: {message.topic} {message.payload.decode()}")
        topic = message.topic
        payload = message.payload.decode()

        topic_parts = topic.split("/")
        device_from_topic = topic_parts[2] if len(topic_parts) > 2 else None
        if self.device_name and device_from_topic and device_from_topic != self.device_name:
            logging.debug(f"Ignoring state for unexpected device '{device_from_topic}' (expecting '{self.device_name}')")
            return
        if not self.device_name and device_from_topic:
            self.device_name = device_from_topic
            logging.info(f"Detected Bluetti device name from topic: {self.device_name}")

        if not self.device_connected:
            self.device_connected = True

        topic_map = {
            "total_battery_percent": ("total_battery_percent", int),
            "ac_output_on": ("ac_output_on", lambda x: x == "ON"),
            "dc_output_on": ("dc_output_on", lambda x: x == "ON"),
            "ac_output_power": ("ac_output_power", int),
            "dc_output_power": ("dc_output_power", int),
            "ac_input_power": ("ac_input_power", float),
            "dc_input_power": ("dc_input_power", float),
        }

        for key, (attr, transform) in topic_map.items():
            if key in topic:
                value = transform(payload)
                self.status.update_status(attr, value)
                break

    def start_client(self):
        self.client.loop_start()

    def start_broker(self):
        """Start the bluetti-mqtt broker as a subprocess."""
        bluetti_exe = shutil.which("bluetti-mqtt")
        if not bluetti_exe:
            logging.error(
                "bluetti-mqtt binary not found on PATH. Install bluetti-mqtt (pip) or run via Docker where it is available."
            )
            return False

        # Clean up any previous broker before starting a new one
        self.stop_broker()

        command = [
            bluetti_exe,
            "--broker",
            self.broker_host,
            "--interval",
            self.broker_interval,
            self.mac_address,
        ]
        if self.broker_adapter:
            logging.warning(
                "BLUETTI_BROKER_ADAPTER is set (%s) but installed bluetti-mqtt does not support --adapter; using default adapter.",
                self.broker_adapter,
            )
        try:
            logging.debug(f"Starting bluetti-mqtt with command: {' '.join(command)}")
            self.broker_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            logging.debug(
                f"Started bluetti-mqtt broker pid={self.broker_process.pid} cmd={' '.join(command)}"
            )

            threading.Thread(
                target=self._pipe_to_log,
                args=(self.broker_process.stdout, logging.debug, "bluetti-mqtt stdout"),
                daemon=True,
            ).start()
            threading.Thread(
                target=self._pipe_to_log,
                args=(self.broker_process.stderr, logging.error, "bluetti-mqtt stderr"),
                daemon=True,
            ).start()
            threading.Thread(
                target=self._log_exit_code,
                daemon=True,
            ).start()

            return True
        except Exception as e:
            logging.error(f"Failed to start bluetti-mqtt broker: {e}")
            return False

    def stop_broker(self):
        """Stop the bluetti-mqtt broker subprocess."""
        if hasattr(self, "broker_process") and self.broker_process:
            self.broker_process.terminate()
            self.broker_process.wait()
            logging.debug("bluetti-mqtt broker stopped successfully.")
            self.broker_process = None
        else:
            logging.debug("No broker process found to stop.")

    def stop_client(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _pipe_to_log(self, pipe, log_func, prefix):
        """Forward a subprocess pipe to logging."""
        if not pipe:
            return
        for line in pipe:
            log_func(f"{prefix}: {line.strip()}")

    def _log_exit_code(self):
        """Wait for broker process to exit and log the return code."""
        if not hasattr(self, "broker_process") or not self.broker_process:
            return
        self.broker_process.wait()
        logging.debug(
            f"bluetti-mqtt broker exited with code {self.broker_process.returncode}"
        )

    def set_ac_output(self, state: str):
        """Turn AC output ON/OFF"""
        if state in ["ON", "OFF"]:
            topic = self._command_topic("ac_output_on")
            if not topic:
                return
            self.client.publish(topic, state)
            self.ac_output_on = state == "ON"
        else:
            logging.debug("Invalid state for AC output")

    def set_dc_output(self, state: str):
        """Turn DC output ON/OFF"""
        if state in ["ON", "OFF"]:
            topic = self._command_topic("dc_output_on")
            if not topic:
                return
            self.client.publish(topic, state)
        else:
            logging.debug("Invalid state for DC output")

    def power_off(self):
        topic = self._command_topic("power_off")
        if topic:
            self.client.publish(topic, "ON")

    def _validate_config(self) -> bool:
        """Validate required configuration before trying to connect."""
        missing = []
        if not self.mac_address:
            missing.append("BLUETTI_MAC_ADDRESS")
        if not self.device_name:
            logging.info("BLUETTI_DEVICE_NAME not set; will auto-detect from MQTT topics.")
        if not self.broker_interval:
            missing.append("BLUETTI_BROKER_INTERVAL")
        if not self.broker_host:
            missing.append("BLUETTI_BROKER_HOST")
        if missing:
            logging.error(f"Missing required Bluetti config values: {', '.join(missing)}")
            return False
        return True

    def _command_topic(self, command_suffix: str) -> str | None:
        """Build a command topic; return None if the device name is unknown."""
        if not self.device_name:
            logging.error("Cannot publish command because BLUETTI_DEVICE_NAME is not set and has not been auto-detected yet.")
            return None
        return f"bluetti/command/{self.device_name}/{command_suffix}"

    def _log_config(self):
        """Log active configuration for easier debugging."""
        logging.debug(
            "Bluetti MQTT config: host=%s interval=%ss timeout=%ss mac=%s adapter=%s device_name=%s",
            self.broker_host,
            self.broker_interval,
            self.broker_connection_timeout,
            self.mac_address,
            self.broker_adapter or "default",
            self.device_name or "auto-detect",
        )
