import subprocess
import os


class MosquittoService:
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
        os.system("sudo systemctl start mosquitto")
        print("Mosquitto started.")
