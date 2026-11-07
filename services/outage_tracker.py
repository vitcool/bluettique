from services.charging_supervisor import ChargingConfig
from services.failure_streak import FailureStreak


class OutageTracker:
    """Tracks whether a Tapo outage was confirmed while waiting, and whether AC keep-alive was sent for it."""

    def __init__(self, config: ChargingConfig):
        self.streak = FailureStreak(config.offline_confirm_failures, config.offline_confirm_sec)
        self.seen = False
        self.keep_alive_sent = False

    def register_failure(self) -> bool:
        return self.streak.register()

    def reset(self):
        self.streak.reset()
        self.keep_alive_sent = False

    def begin_wait(self):
        """Require a fresh offline->online observation."""
        self.seen = False
        self.reset()
