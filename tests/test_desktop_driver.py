import ctypes
from contextlib import nullcontext
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from desktop_driver import DesktopDriver, MacAccessibility, WindowsDesktop, _Point, linux_tree


class DesktopDriverTests(unittest.TestCase):
    def setUp(self):
        with patch("desktop_driver.shutil.which", return_value=None):
            self.linux = DesktopDriver(None, "linux")

    def test_x11_chord_normalizes_modifiers_and_punctuation(self):
        with patch("desktop_driver.os_command") as command:
            self.linux.press(["period", "Shift"])
        command.assert_called_once_with("xdotool", "key", "--clearmodifiers", "Shift_L+period", read=False)

    def test_x11_duplicate_and_unknown_keys_are_rejected_before_input(self):
        for keys in (["ctrl", "Control", "a"], ["keydown"], ["--help"]):
            with self.subTest(keys=keys), patch("desktop_driver.os_command") as command:
                with self.assertRaises(ValueError):
                    self.linux.press(keys)
                command.assert_not_called()

    def test_drag_releases_pressed_button_on_movement_failure(self):
        self.linux.mouse_event = Mock()
        self.linux.move = Mock(side_effect=[None, OSError("movement failed")])
        with self.assertRaises(OSError):
            self.linux.drag({"x": 10, "y": 20, "end_x": 30, "end_y": 40, "button": "right"})
        self.assertEqual(
            self.linux.mouse_event.call_args_list,
            [call("down", (10, 20), "right"), call("up", (30, 40), "right")],
        )

    def test_unicode_text_replacement_uses_clipboard_then_keyboard_paste(self):
        value = "مرحبًا 🌍 café\nلوحة المفاتيح ١٢٣"
        self.linux.press = Mock()
        self.linux.clipboard_write = Mock()
        self.linux.insert(value, True)
        self.assertEqual(self.linux.press.call_args_list, [call(["ctrl", "a"]), call(["ctrl", "v"])])
        self.linux.clipboard_write.assert_called_once_with(value)

    def test_clipboard_text_rejects_nul_before_reaching_native_tool(self):
        with patch("desktop_driver.os_command") as command:
            with self.assertRaises(ValueError):
                self.linux.clipboard_write("text\x00tail")
            command.assert_not_called()

    def test_window_list_keeps_whitespace_and_multilingual_titles(self):
        output = b"0x0010012a 0 100 20 30 400 500 host " + "Editor عنوان 🌍".encode() + b"\n"
        with patch("desktop_driver.os_command", return_value=output):
            self.assertEqual(self.linux.windows(), [{
                "id": "0x0010012a", "process_id": 100, "title": "Editor عنوان 🌍",
                "bounds": {"x": 20, "y": 30, "width": 400, "height": 500},
            }])

    def test_windows_clipboard_reads_only_terminated_unicode_text(self):
        content = "العربية 🌍\r\nsecond"
        encoded = (content + "\x00").encode("utf-16-le") + b"\x00\xd8"
        storage = ctypes.create_string_buffer(encoded, len(encoded))
        driver = WindowsDesktop.__new__(WindowsDesktop)
        driver.memory = SimpleNamespace(GlobalSize=lambda _: len(encoded))
        driver.user = SimpleNamespace(IsClipboardFormatAvailable=lambda _: True, GetClipboardData=lambda _: 1)
        driver.clipboard = nullcontext
        driver.global_buffer = lambda _: nullcontext(ctypes.addressof(storage))
        self.assertEqual(driver.clipboard_read(), "العربية 🌍\nsecond")

    def test_mac_window_geometry_releases_temporary_cf_objects_on_failure(self):
        driver = MacAccessibility.__new__(MacAccessibility)
        driver.native = SimpleNamespace(
            AXValueCreate=Mock(return_value=100),
            AXUIElementSetAttributeValue=Mock(return_value=-25205),
        )
        driver.objc = SimpleNamespace(pyobjc_id=Mock(return_value=101))
        driver.cf = SimpleNamespace(
            CFStringCreateWithCString=Mock(return_value=102),
            CFRelease=Mock(),
        )
        with self.assertRaises(OSError):
            driver.set_dimensions(object(), "AXPosition", 1, _Point(10, 20))
        driver.native.AXUIElementSetAttributeValue.assert_called_once_with(101, 102, 100)
        self.assertEqual(driver.cf.CFRelease.call_args_list, [call(102), call(100)])

    def test_linux_snapshot_does_not_read_password_value_or_children(self):
        state = Mock()
        state.contains.return_value = True
        password = Mock()
        password.name = "private"
        password.getRole.return_value = "password"
        password.getRoleName.return_value = "password text"
        password.getState.return_value = state
        password.queryComponent.return_value.getExtents.return_value = SimpleNamespace(
            x=10, y=20, width=40, height=30
        )
        desktop = SimpleNamespace(getDesktop=lambda _: [[password]])
        module = SimpleNamespace(
            Registry=desktop, ROLE_PASSWORD_TEXT="password", STATE_SHOWING="showing",
            STATE_ACTIVE="active", STATE_ENABLED="enabled", DESKTOP_COORDS="desktop",
        )
        with patch.dict(sys.modules, {"pyatspi": module}):
            snapshot = linux_tree()
        self.assertEqual(snapshot["nodes"][0]["name"], "")
        self.assertEqual(snapshot["nodes"][0]["text"], "")
        password.queryText.assert_not_called()
