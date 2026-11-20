"""Fail closed if the Actions step holding the job open stops renewing."""

import time


class HoldLease:
    heartbeat = "hold-heartbeat"

    def __init__(self, directory, clock=time.monotonic, startup_grace=75, stale_after=14):
        self.marker = directory / self.heartbeat
        self.clock = clock
        self.last_seen = clock()
        self.stamp = None
        self.startup_grace = startup_grace
        self.stale_after = stale_after

    def active(self):
        now = self.clock()
        try:
            stamp = self.marker.stat().st_mtime_ns
        except FileNotFoundError:
            stamp = None
        if stamp is not None and stamp != self.stamp:
            self.stamp = stamp
            self.last_seen = now
        budget = self.stale_after if self.stamp is not None else self.startup_grace
        return now - self.last_seen < budget
