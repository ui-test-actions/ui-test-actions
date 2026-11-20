import json
import sys
import time
import unittest

from app_processes import DesktopApps
from contract import CommandError


class Fake:
    def capabilities(self):
        return ["pointer.click"]


class AppProcessTests(unittest.TestCase):
    def test_detects_child_exit_and_restarts_only_managed_process(self):
        apps = DesktopApps(Fake(), json.dumps({
            "fixture": {"argv": [sys.executable, "-c", "import time; time.sleep(.4); raise SystemExit(17)"]},
        }))
        self.addCleanup(apps.close)
        with self.assertRaises(CommandError):
            apps.execute("app.launch", {"id": "unconfigured"})
        self.assertTrue(apps.execute("app.launch", {"id": "fixture"})["running"])
        original = apps.running["fixture"]
        self.assertTrue(apps.execute("app.launch", {"id": "fixture"})["running"])
        self.assertIs(apps.running["fixture"], original)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and original.poll() is None:
            time.sleep(.05)
        self.assertEqual(apps.execute("app.status", {"id": "fixture"})["exit_code"], 17)
        self.assertTrue(apps.execute("app.restart", {"id": "fixture"})["running"])
        self.assertIsNot(apps.running["fixture"], original)
        self.assertFalse(apps.execute("app.close", {"id": "fixture"})["running"])
