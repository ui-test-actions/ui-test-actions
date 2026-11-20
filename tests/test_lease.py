from pathlib import Path
import tempfile
import unittest

from lease import HoldLease


class HoldLeaseTests(unittest.TestCase):
    def test_missing_initial_holder_expires(self):
        with tempfile.TemporaryDirectory() as temp:
            now = [0]
            lease = HoldLease(Path(temp), clock=lambda: now[0], startup_grace=5)
            now[0] = 4
            self.assertTrue(lease.active())
            now[0] = 5
            self.assertFalse(lease.active())

    def test_lost_holder_expires_and_keeps_last_observation_when_marker_disappears(self):
        with tempfile.TemporaryDirectory() as temp:
            now = [0]
            lease = HoldLease(Path(temp), clock=lambda: now[0], stale_after=4)
            lease.marker.touch()
            self.assertTrue(lease.active())
            lease.marker.unlink()
            now[0] = 3
            self.assertTrue(lease.active())
            now[0] = 4
            self.assertFalse(lease.active())
