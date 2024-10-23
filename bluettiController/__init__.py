import os
import subprocess
import time
import asyncio
import paho.mqtt.client as mqtt


class Mosquitto:
    def check(self):
        try:
            status_output = (
                subprocess.check_output(["systemctl", "is-active", "mosquitto"])
                .decode("utf-8")
                .strip()
            )
            if status_output == "active":
                print("Mosquitto is running.")
            else:
                print("Mosquitto is not running, starting it...")
                self.start_mosquitto()
        except subprocess.CalledProcessError:
            print("Mosquitto is not installed or not found.")
            self.start_mosquitto()

    def start_mosquitto(self):
        # Start Mosquitto service
        os.system("sudo systemctl start mosquitto")
        print("Mosquitto started.")


class BluettiStatus:
    def __init__(self):
        """Initialize all status attributes."""
        self.total_battery_percent = None
        self.ac_output_on = None
        self.dc_output_on = None
        self.ac_output_power = None
        self.dc_output_power = None
        self.ac_input_power = None
        self.dc_input_power = None
        self.info_received = False

    def update_status(self, attr, value):
        """Update the status attribute with the given value."""

        if not self.info_received:
            self.info_received = True

        setattr(self, attr, value)
        print(f"Bluetti status updated: {attr} = {value}")

    def get_status(self):
        """Return the current status of the Bluetti device as a dictionary."""
        return {
            "total_battery_percent": self.total_battery_percent,
            "ac_output_on": self.ac_output_on,
            "dc_output_on": self.dc_output_on,
            "ac_output_power": self.ac_output_power,
            "dc_output_power": self.dc_output_power,
            "ac_input_power": self.ac_input_power,
            "dc_input_power": self.dc_input_power,
            "info_received": self.info_received,
        }

    def reset_status(self):
        """Reset all status attributes to None (or default values)."""
        self.total_battery_percent = None
        self.ac_output_on = None
        self.dc_output_on = None
        self.ac_output_power = None
        self.dc_output_power = None
        self.ac_input_power = None
        self.dc_input_power = None
        self.device_connected = False
        self.info_received = False
        print("Bluetti status reset to default.")


class BluettiMQTTService:
    def __init__(self):
        self.broker_host = os.getenv("BLUETTI_BROKER_HOST")
        self.mac_address = os.getenv("BLUETTI_MAC_ADDRESS")
        self.device_name = os.getenv("BLUETTI_DEVICE_NAME")
        self.broker_interval = os.getenv("BLUETTI_BROKER_INTERVAL")
        self.broker_connection_timeout = os.getenv("BLUETTI_BROKER_CONNECTION_TIMEOUT")
        self.client = mqtt.Client()

        # Subscribe to necessary topics
        self.subscribe_topic = f"bluetti/state/{self.device_name}/#"
        self.dc_command_topic = f"bluetti/command/{self.device_name}/dc_output_on"
        self.ac_command_topic = f"bluetti/command/{self.device_name}/ac_output_on"
        self.power_off_topic = f"bluetti/command/{self.device_name}/power_off"

        self.device_connected = False
        self.status = BluettiStatus()

    async def connect(self):
        if self.device_connected:
            self.device_connected = False
        self.start_broker()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.broker_host)
        self.start_client()
        try:
            await asyncio.wait_for(
                self._wait_for_pairing(), timeout=int(self.broker_connection_timeout)
            )
            return True
        except asyncio.TimeoutError:
            self.stop_broker()
            self.stop_client()
            return False

    async def _wait_for_pairing(self):
        while not self.device_connected:
            await asyncio.sleep(0.1)

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Connected to broker")
            client.subscribe(self.subscribe_topic)
        else:
            print(f"Failed to connect, return code {rc}")

    def on_message(self, client, userdata, message):
        topic = message.topic
        payload = message.payload.decode()

        # Print the whole topic message
        print(f"Received message on topic {topic}: {payload}")

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
        command = [
            "sudo",
            "bluetti-mqtt",
            "--broker",
            self.broker_host,
            "--interval",
            self.broker_interval,
            self.mac_address,
        ]
        try:
            # Start the broker in the background
            self.broker_process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            print(
                f"bluetti-mqtt broker started successfully with MAC address: {self.mac_address}"
            )
        except Exception as e:
            print(f"Failed to start bluetti-mqtt broker: {e}")

    def stop_broker(self):
        """Stop the bluetti-mqtt broker subprocess."""
        if hasattr(self, "broker_process") and self.broker_process:
            self.broker_process.terminate()
            self.broker_process.wait()
            print("bluetti-mqtt broker stopped successfully.")
        else:
            print("No broker process found to stop.")

    def stop_client(self):
        self.client.loop_stop()
        self.client.disconnect()

    def set_ac_output(self, state: str):
        """Turn AC output ON/OFF"""
        if state in ["ON", "OFF"]:
            self.client.publish(self.ac_command_topic, state)
            self.ac_output_on = state == "ON"
        else:
            print("Invalid state for AC output")

    def set_dc_output(self, state: str):
        """Turn DC output ON/OFF"""
        if state in ["ON", "OFF"]:
            self.client.publish(self.dc_command_topic, state)
        else:
            print("Invalid state for DC output")

    def power_off(self):
        self.client.publish(self.power_off_topic, "ON")


class BluettiController:
    def __init__(self):
        self.mosquitto = Mosquitto()
        self.bluetti = BluettiMQTTService()
        self.turned_on = True
        self.connection_set = False
        self.ac_turned_on = False
        self.dc_turned_on = False

    async def initialize(self):
        self.mosquitto.check()
        print("BluettiController initialized.")
        for attempt in range(2):
            if await self.bluetti.connect():
                print("BluettiMQTTService connected.")
                self.connection_set = True
            print(
                f"Retrying connection to BluettiMQTTService... (Attempt {attempt + 1})"
            )
            await asyncio.sleep(5)
        print("Failed to connect to BluettiMQTTService after 2 attempts.")
        return False

    def turn_dc(self, state: str):
        print("Bluetti: Turning DC device", state)
        self.dc_turned_on = state == "ON"
        self.bluetti.set_dc_output(state)

    def turn_ac(self, state: str):
        print("Bluetti: Turning AC device", state)
        self.ac_turned_on = state == "ON"
        self.bluetti.set_ac_output(state)

    def power_off(self):
        print("Bluetti: Turning off device")
        # self.bluetti.power_off() sometimes it works, sometimes it doesn't
        self.stop()
        # self.bluetti.reset_status()
        self.turned_on = False
        self.connection_set = False

    def get_status(self):
        return self.bluetti.status.get_status()

    def stop(self):
        self.bluetti.stop_client()
        self.bluetti.stop_broker()
