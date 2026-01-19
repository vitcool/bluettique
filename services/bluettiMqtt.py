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
        self.broker_host = os.getenv("BLUETTI_BROKER_HOST")
        self.mac_address = os.getenv("BLUETTI_MAC_ADDRESS")
        self.device_name = os.getenv("BLUETTI_DEVICE_NAME")
        self.broker_interval = os.getenv("BLUETTI_BROKER_INTERVAL")
        self.broker_connection_timeout = max(
            int(os.getenv("BLUETTI_BROKER_CONNECTION_TIMEOUT", "60")), 30
        )
        self.broker_adapter = os.getenv("BLUETTI_BROKER_ADAPTER")
        self.client = mqtt.Client()

        # Subscribe to necessary topics
        self.subscribe_topic = f"bluetti/state/{self.device_name}/#"
        self.dc_command_topic = f"bluetti/command/{self.device_name}/dc_output_on"
        self.ac_command_topic = f"bluetti/command/{self.device_name}/ac_output_on"
        self.power_off_topic = f"bluetti/command/{self.device_name}/power_off"

        self.device_connected = False
        self.status = BluettiStatus()

    async def connect(self):
        try:
            if self.device_connected:
                self.device_connected = False
            if not self.start_broker():
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
                return False
        except Exception as e:
            logging.debug(f"Exception occurred during connection: {e}")
            self.stop_client()
            return False

    async def _wait_for_pairing(self):
        while not self.device_connected:
            await asyncio.sleep(0.1)

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(self.subscribe_topic)
            logging.debug(f"CONNECTED to {self.broker_host}")
        else:
            logging.debug(f"Failed to connect, return code {rc}")

    def on_message(self, client, userdata, message):
        logging.info(f"Received message: {message.topic} {message.payload.decode()}")
        topic = message.topic
        payload = message.payload.decode()

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
            command.extend(["--adapter", self.broker_adapter])
        try:
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
            self.client.publish(self.ac_command_topic, state)
            self.ac_output_on = state == "ON"
        else:
            logging.debug("Invalid state for AC output")

    def set_dc_output(self, state: str):
        """Turn DC output ON/OFF"""
        if state in ["ON", "OFF"]:
            self.client.publish(self.dc_command_topic, state)
        else:
            logging.debug("Invalid state for DC output")

    def power_off(self):
        self.client.publish(self.power_off_topic, "ON")
