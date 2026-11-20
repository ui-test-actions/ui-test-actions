from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from contract import CommandError
from mobile_environment import MobileEnvironment


APP = "dev.uitest.fixture"


class MobileEnvironmentTest(TestCase):
    def test_android_locales_report_actual_value_and_restore_previous(self):
        shell = Mock(side_effect=[b"Locales for dev.uitest.fixture for user 0 are [en-US,fr-FR]",
                                  b"", b"Locales for dev.uitest.fixture for user 0 are [ar-SA]",
                                  b"", b"Locales for dev.uitest.fixture for user 0 are [en-US,fr-FR]"])
        driver = SimpleNamespace(target="android", app_ids={APP}, legacy=SimpleNamespace(adb=["emulator-5554"]),
                                 shell=shell)
        environment = MobileEnvironment(driver, '{"dev.uitest.fixture":[]}')
        self.assertEqual(environment.execute("app.locale.set", {"id": APP, "locale": "ar-SA"})["locale"], "ar-SA")
        environment.close()
        shell.assert_any_call("cmd", "locale", "set-app-locales", APP, "--locales", "ar-SA")
        shell.assert_any_call("cmd", "locale", "set-app-locales", APP, "--locales", "en-US,fr-FR")

    def test_simulator_changes_are_scoped_and_touched_permission_is_reset(self):
        driver = SimpleNamespace(target="ios", app_ids={APP}, simctl=Mock(), _launch_simulator=Mock())
        environment = MobileEnvironment(driver, '{"dev.uitest.fixture":["photos"]}')
        environment.execute("app.locale.set", {"id": APP, "locale": "ar-SA"})
        driver._launch_simulator.assert_called_once_with(APP, "ar-SA")
        with self.assertRaises(CommandError):
            environment.execute("app.permission.set", {"id": APP, "permission": "contacts", "state": "denied"})
        response = environment.execute("app.permission.set", {"id": APP, "permission": "photos", "state": "denied"})
        self.assertEqual(response["source"], "simulator:privacy")
        self.assertFalse(response["verified_by_driver"])
        environment.close()
        self.assertEqual(driver.simctl.call_count, 2)
        driver.simctl.assert_any_call("privacy", "revoke", "photos", APP)
        driver.simctl.assert_any_call("privacy", "reset", "photos", APP, timeout=4)

    def test_permission_probe_reads_only_user_zero(self):
        output = (b"  User 0: installed=true\n      android.permission.CAMERA: granted=false, flags=[]\n"
                  b"  User 8: installed=true\n      android.permission.CAMERA: granted=true, flags=[]\n"
                  b"Queries:\n  User 0:\n    android.permission.CAMERA: granted=true\n")
        driver = SimpleNamespace(target="android", app_ids={APP}, legacy=SimpleNamespace(adb=["emulator-5554"]),
                                 shell=Mock(return_value=output))
        environment = MobileEnvironment(driver, '{"dev.uitest.fixture":["camera"]}')
        self.assertFalse(environment.android_permission(APP, "android.permission.CAMERA"))

    def test_permission_probe_accepts_default_denial_for_a_declared_permission(self):
        output = (b"    requested permissions:\n      android.permission.CAMERA\n"
                  b"    install permissions:\n      android.permission.INTERNET: granted=true\n"
                  b"    User 0: installed=true hidden=false\n      runtime permissions:\n"
                  b"Queries:\n  User 0:\n")
        driver = SimpleNamespace(target="android", app_ids={APP}, legacy=SimpleNamespace(adb=["emulator-5554"]),
                                 shell=Mock(return_value=output))
        environment = MobileEnvironment(driver, '{"dev.uitest.fixture":["camera"]}')
        self.assertFalse(environment.android_permission(APP, "android.permission.CAMERA"))
        with self.assertRaises(CommandError):
            environment.android_permission(APP, "android.permission.READ_CONTACTS")
