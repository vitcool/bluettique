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
        self.broker_interval = os.getenv("BLUETTI_BROKER_INTERVAL")
        self.broker_connection_timeout = os.getenv("BLUETTI_BROKER_CONNECTION_TIMEOUT")
        self.client = mqtt.Client()

        # Subscribe to necessary topics
        self.subscribe_topic = f"bluetti/state/{self.device_name}/#"
        self.dc_command_topic = f"bluetti/command/{self.device_name}/dc_output_on"
        self.ac_command_topic = f"bluetti/command/{self.device_name}/ac_output_on"

        self.device_connected = False

    async def connect(self):
        self.start_broker()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.broker_host)
        self.start_client()
        try:
            await asyncio.wait_for(self._wait_for_pairing(), timeout=int(self.broker_connection_timeout))
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

        self.device_connected = True
        # Update properties based on received messages
        if "total_battery_percent" in topic:
            self.total_battery_percent = int(payload)
            print(f"Battery Percent: {self.total_battery_percent}")
        elif "ac_output_on" in topic:
            self.ac_output_on = payload == "ON"
            print(f"AC Output: {self.ac_output_on}")
        elif "dc_output_on" in topic:
            self.dc_output_on = payload == "ON"
            print(f"DC Output: {self.dc_output_on}")
            
    def get_status(self):
        return {
            "total_battery_percent": getattr(self, "total_battery_percent", None),
            "ac_output_on": getattr(self, "ac_output_on", None),
            "dc_output_on": getattr(self, "dc_output_on", None),
        }

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
        if hasattr(self, 'broker_process') and self.broker_process:
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
        
    async def get_status(self):
        return self.bluetti.get_status()

    def stop(self): 
        self.bluetti.stop_client()
        self.bluetti.stop_broker()
