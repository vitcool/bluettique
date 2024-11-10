import logging

class TapoStatus:
    def __init__(self, online=False, charging=False):
        self.online = online
        self.charging = charging

    def set_online(self, online: bool):
        """Set the online status and handle any additional logic."""
        self.online = online

    def set_charging(self, charging: bool):
        """Set the charging status and handle any additional logic."""
        self.charging = charging

    def reset(self):
        """Reset the status to its default values."""
        self.online = False
        self.charging = False
        logging.debug("Tapo status reset to default.")

    def get_status(self):
        """Get the current status as an object with properties 'online' and 'charging'."""
        return {"online": self.online, "charging": self.charging}
