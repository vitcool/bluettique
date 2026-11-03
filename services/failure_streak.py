import time


class FailureStreak:
    """Counts consecutive failures; confirmed after `max_failures` of them or `max_sec` since the first."""

    def __init__(self, max_failures: int, max_sec: float):
        self.max_failures = max_failures
        self.max_sec = max_sec
        self.count = 0
        self.since: float | None = None

    def register(self) -> bool:
        now = time.monotonic()
        if self.since is None:
            self.since = now
        self.count += 1
        return self.count >= self.max_failures or now - self.since >= self.max_sec

    def reset(self):
        self.count = 0
        self.since = None
