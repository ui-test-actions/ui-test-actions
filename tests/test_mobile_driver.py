import base64
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from mobile import open_simulator
from mobile_driver import AndroidIme, MobileDriver, parse_android_tree


class SimulatorStartupTest(unittest.TestCase):
    def test_retries_a_slow_inventory_and_reuses_the_checked_device(self):
        inventory = ("xcrun", "simctl", "list", "devices", "booted", "-j")
        devices = b'{"devices":{"com.apple.SimRuntime.iOS-26":[{"udid":"ios-test","state":"Booted"}]}}'
        with patch("mobile.output", side_effect=[subprocess.TimeoutExpired(inventory, 20), devices, b""]) as native:
            selected = open_simulator("ios-test")
        self.assertEqual(native.call_args_list, [
            call(*inventory, timeout=20),
            call(*inventory, timeout=40),
            call("open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", "ios-test", timeout=20),
        ])
        with patch.dict(os.environ, {}, clear=True), patch("mobile_driver._run") as query:
            driver = MobileDriver(Mock(), "ios", checked_ios_device=selected)
        self.assertEqual(driver.device, "ios-test")
        query.assert_not_called()

    def test_retries_a_slow_simulator_window_launch(self):
        devices = b'{"devices":{"com.apple.SimRuntime.iOS-26":[{"udid":"ios-test","state":"Booted"}]}}'
        launch = ("open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", "ios-test")
        with patch("mobile.output", side_effect=[devices, subprocess.TimeoutExpired(launch, 20), b""]) as native:
            self.assertEqual(open_simulator("ios-test"), "ios-test")
        self.assertEqual(native.call_args_list[-2:], [call(*launch, timeout=20), call(*launch, timeout=40)])


class AndroidTreeTest(unittest.TestCase):
    def test_normalizes_tree_and_redacts_password_fields(self):
        data = b"""<hierarchy rotation="0">
          <node class="android.widget.FrameLayout" bounds="[0,0][320,640]" enabled="true">
            <node class="android.widget.Button" text="Apply" content-desc="Action"
              resource-id="fixture:id/apply" bounds="[20,40][240,80]" enabled="true" clickable="true"/>
            <node class="android.widget.EditText" text="private value" content-desc="private description"
              bounds="[4,0][300,40]" password="true" enabled="false"/>
          </node>
        </hierarchy>"""
        root, button, password = parse_android_tree(data)["nodes"]
        self.assertEqual(button["parent_id"], root["id"])
        self.assertEqual(button["role"], "button")
        self.assertEqual(button["name"], "Action")
        self.assertEqual(button["resource_id"], "fixture:id/apply")
        self.assertEqual(button["bounds"], {"x": 20, "y": 40, "width": 220, "height": 40})
        self.assertTrue(button["visible"])
        self.assertFalse(password["enabled"])
        self.assertEqual((password["text"], password["name"]), ("", ""))
        self.assertTrue(password["properties"]["password"])

    def test_rejects_malformed_tree_or_entities(self):
        for data in (b"<hierarchy", b'<!DOCTYPE tree [ <!ENTITY x "secret"> ]><tree />'):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                parse_android_tree(data)


class AndroidDriverTest(unittest.TestCase):
    def setUp(self):
        legacy = Mock()
        legacy.adb = ("adb", "-s", "emulator-5554")
        legacy.capture.return_value = b"\x89PNG\r\n\x1a\n" + bytes(8) + struct.pack(">II", 400, 800)
        environment = {
            "UI_TEST_ANDROID_IME": "0",
            "UI_TEST_APP_IDS": "dev.uitest.fixture",
            "UI_TEST_DEEPLINK_SCHEMES": "app-test",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.driver = MobileDriver(legacy, "android")
        self.driver.shell = Mock(return_value=b"Status: ok")

    def test_app_operations_refuse_unconfigured_package(self):
        with self.assertRaises(ValueError):
            self.driver.execute("app.reset", {"id": "com.android.settings"})
        self.driver.shell.assert_not_called()
        self.assertNotIn("app.install", self.driver.capabilities())
        self.assertNotIn("clipboard.set", self.driver.capabilities())

    def test_app_install_verifies_configured_apk_package(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "fixture.apk"
            artifact.touch()
            self.driver.install_paths = {"dev.uitest.fixture": str(artifact)}
            self.driver.adb = Mock()
            with patch.dict(os.environ, {"ANDROID_HOME": "/sdk"}, clear=True), patch(
                "mobile_driver._run", return_value=b"package: name='unexpected' versionCode='1' "
            ):
                with self.assertRaises(ValueError):
                    self.driver.execute("app.install", {"id": "dev.uitest.fixture"})
            self.driver.adb.assert_not_called()

    def test_allowlisted_deep_link_remains_single_shell_argument(self):
        url = "app-test://test/path?a=Arabic%20%26%20English&next=%27"
        self.driver.execute("app.deeplink", {"url": url, "id": "dev.uitest.fixture"})
        self.driver.shell.assert_called_once_with(
            "am", "start", "-W", "-a", "android.intent.action.VIEW", "-d", url, "-p",
            "dev.uitest.fixture",
        )
        self.driver.shell.reset_mock()
        with self.assertRaises(ValueError):
            self.driver.execute("app.deeplink", {"url": "file:///etc/passwd"})
        self.driver.shell.assert_not_called()

    def test_scroll_and_keyboard_chord(self):
        self.driver.execute("pointer.scroll", {"x": 300, "y": 500, "dx": 1, "dy": 10})
        self.driver.shell.assert_called_with("input", "swipe", "300", "500", "276", "260", "330")
        self.driver.execute("keyboard.press", {"keys": ["Ctrl", "Shift", "ArrowLeft"]})
        self.driver.shell.assert_called_with(
            "input", "keycombination", "KEYCODE_CTRL_LEFT", "KEYCODE_SHIFT_LEFT", "KEYCODE_DPAD_LEFT",
        )
        with self.assertRaises(ValueError):
            self.driver.execute("keyboard.press", {"keys": ["a", "b"]})

    def test_orientation_cleanup_restores_previous_settings(self):
        self.driver.shell.side_effect = [b"1\n", b"0\n", b"", b"", b"", b""]
        result = self.driver.execute("device.orientation", {"orientation": "landscape"})
        self.assertEqual(result, {"orientation": "landscape"})
        self.driver.close()
        self.assertEqual(self.driver.shell.call_args_list[-2:], [
            call("settings", "put", "system", "accelerometer_rotation", "1", timeout=3),
            call("settings", "put", "system", "user_rotation", "0", timeout=3),
        ])


class UnicodeTest(unittest.TestCase):
    text = "العربية English ٢٠٢٦،\n🙂"

    def test_android_ime_escapes_transport_and_round_trips_utf8(self):
        driver = Mock()
        ime = AndroidIme(driver)
        ime.active = True
        encoded = base64.b64encode(self.text.encode("utf-8")).decode("ascii")
        driver.shell.return_value = f'Broadcast completed: result=42, data="{encoded}"'.encode()
        self.assertEqual(ime.execute("clipboard.get"), self.text)
        ime.execute("clipboard.set", self.text)
        args = driver.shell.call_args.args
        self.assertEqual(args[-3:], ("--es", "payload", encoded))
        self.assertNotIn(self.text, args)

    def test_android_ime_cleanup_uninstalls_even_when_restore_fails(self):
        driver = Mock()
        driver.shell.side_effect = [RuntimeError("restore failed"), b""]
        ime = AndroidIme(driver)
        ime.previous = "com.android.inputmethod.latin/.LatinIME"
        ime.installed = True
        with self.assertRaises(RuntimeError):
            ime.close()
        driver.adb.assert_called_once_with("uninstall", "dev.uitest.sessionime", timeout=5)

    def test_ios_uses_device_clipboard_and_paste_for_unicode(self):
        legacy = Mock()
        devices_json = b'{"devices":{"com.apple.CoreSimulator.SimRuntime.iOS-26-2":[{"udid":"sim","state":"Booted"}]}}'
        with patch.dict(os.environ, {}, clear=True), patch("mobile_driver._run", return_value=devices_json):
            driver = MobileDriver(legacy, "ios")
        driver._require_simulator_focus = Mock()
        driver.simctl = Mock(return_value=self.text.encode("utf-8"))
        driver.execute("text.insert", {"text": self.text, "replace": True})
        driver._require_simulator_focus.assert_called_once_with()
        driver.simctl.assert_called_once_with("pbcopy", stdin=self.text.encode("utf-8"))
        self.assertEqual(legacy.gui.hotkey.call_args_list, [call("command", "a"), call("command", "v")])
        self.assertEqual(driver.execute("clipboard.get", {}), {"text": self.text})


if __name__ == "__main__":
    unittest.main()
