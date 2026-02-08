import logging

class BluettiStatus:
    def __init__(self):
        """Initialize all status attributes."""
        self.total_battery_percent = None
        self.pack_details2_percent = None
        self.pack_details2_voltage = None
        self.pack_details3_percent = None
        self.pack_details3_voltage = None
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

    def get_status(self):
        """Return the current status of the Bluetti device as a dictionary."""
        return {
            "total_battery_percent": self.total_battery_percent,
            "pack_details2_percent": self.pack_details2_percent,
            "pack_details2_voltage": self.pack_details2_voltage,
            "pack_details3_percent": self.pack_details3_percent,
            "pack_details3_voltage": self.pack_details3_voltage,
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
        self.pack_details2_percent = None
        self.pack_details2_voltage = None
        self.pack_details3_percent = None
        self.pack_details3_voltage = None
        self.ac_output_on = None
        self.dc_output_on = None
        self.ac_output_power = None
        self.dc_output_power = None
        self.ac_input_power = None
        self.dc_input_power = None
        self.device_connected = False
        self.info_received = False
        logging.debug("Bluetti status reset to default.")

    def reset_output_status(self):
        self.ac_output_on = False
        self.dc_output_on = False
