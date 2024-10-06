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


class BluettiMQTTService:
    def __init__(self):
        self.broker_host = os.getenv("BLUETTI_BROKER_HOST")
        self.mac_address = os.getenv("BLUETTI_MAC_ADDRESS")
        self.device_name = os.getenv("BLUETTI_DEVICE_NAME")
        self.client = mqtt.Client()

        # Subscribe to necessary topics
        self.subscribe_topic = f"bluetti/state/{self.device_name}/#"
        self.dc_command_topic = f"bluetti/command/{self.device_name}/dc_output_on"
        self.ac_command_topic = f"bluetti/command/{self.device_name}/ac_output_on"

        self.device_connected = False

    async def connect(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.broker_host)
        self.start()
        time.sleep(1)
        self.set_dc_output("ON")
        time.sleep(1)
        self.set_dc_output("OFF")
        try:
            await asyncio.wait_for(self._wait_for_pairing(), timeout=20)
            print("Pairing successful")
        except asyncio.TimeoutError:
            print("Timeout waiting for pairing")

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

        print(f"Received message: {topic} - {payload}")
        self.device_connected = True

        # Print or process the data fields you're interested in
        if "total_battery_percent" in topic:
            print(f"Battery Percent: {payload}")
        elif "ac_output_on" in topic:
            print(f"AC Output: {payload}")
        elif "dc_output_on" in topic:
            print(f"DC Output: {payload}")

    def start(self):
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def set_ac_output(self, state: str):
        """Turn AC output ON/OFF"""
        if state in ["ON", "OFF"]:
            self.client.publish(self.ac_command_topic, state)
        else:
            print("Invalid state for AC output")

    def set_dc_output(self, state: str):
        """Turn DC output ON/OFF"""
        if state in ["ON", "OFF"]:
            self.client.publish(self.dc_command_topic, state)
        else:
            print("Invalid state for DC output")


class BluettiController:
    def __init__(self):
        self.mosquitto = Mosquitto()
        self.bluetti = BluettiMQTTService()

    async def initialize(self):
        self.mosquitto.check()
        print("BluettiController initialized.")
        await self.bluetti.connect()

    def turn_dc(self):
        print("Bluetti:Turning DC device on...")
        self.bluetti.set_dc_output("ON")
        time.sleep(2)
        self.bluetti.set_dc_output("OFF")
        print("Bluetti:Turning DC device off...")
