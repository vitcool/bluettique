import threading
import time
import logging
from utils.power_outage_api import fetch_electricity_outages, mock_fetch_function
from utils.schedule_formatter import run_format

class ScheduleManager:
    def __init__(self):
        self.outage_schedule = []  # Store the outage times
        self.lock = threading.Lock()  # Thread-safe updates

    def fetch_schedule(self):
        # Simulate fetching the schedule from an API
        new_schedule = fetch_electricity_outages()
        new_schedule_formatted = run_format(new_schedule)
        logging.info(f"New schedule: {new_schedule_formatted}")
        with self.lock:
            self.outage_schedule = new_schedule_formatted

    def is_outage_expected(self):
        # Check if the current time falls within an outage period
        current_hour = time.localtime().tm_hour
        logging.info(f"current_hour: {current_hour}")
        with self.lock:
            for period in self.outage_schedule:
                if period["start"] <= current_hour < period["end"]:
                    return True
        return False

    def start_periodic_updates(self):
        def update_loop():
            while True:
                self.fetch_schedule()
                time.sleep(3600)  # Update every hour

        threading.Thread(target=update_loop, daemon=True).start()














