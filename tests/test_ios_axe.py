import unittest
from unittest.mock import Mock

from contract import CommandError
from ios_axe import AxeSimulator, source_tree


class IosAxeTests(unittest.TestCase):
    def test_clips_bounds_and_omits_secure_values_and_children(self):
        result = source_tree([{
            "role": "AXApplication",
            "children": [
                {"role": "AXButton", "AXUniqueId": "save", "AXLabel": "حفظ",
                 "frame": {"x": 90, "y": 20, "width": 20, "height": 20}},
                {"role": "AXTextField", "subrole": "AXSecureTextField", "AXValue": "sensitive value",
                 "children": [{"AXLabel": "secret child"}]},
                {"role": "AXButton", "frame": {"x": 90, "y": 120, "width": 20, "height": 20}},
            ],
        }], (100, 100))
        app, button, secret, offscreen = result["nodes"]
        self.assertEqual(button["parent_id"], app["id"])
        self.assertEqual(button["resource_id"], "save")
        self.assertEqual(button["name"], "حفظ")
        self.assertEqual(button["bounds"], {"x": 90, "y": 20, "width": 10, "height": 20})
        self.assertTrue(secret["properties"]["password"])
        self.assertEqual(secret["text"], "")
        self.assertFalse(offscreen["visible"])

    def test_unicode_uses_the_simulator_pasteboard_and_native_chords(self):
        driver = object.__new__(AxeSimulator)
        driver.mobile = Mock()
        driver.axe = Mock()
        text = "مَرْحَبًا ١٢٣ 🌍\nMixed English"
        driver.execute("text.insert", {"text": text, "replace": True})
        driver.mobile.execute.assert_called_once_with("clipboard.set", {"text": text})
        self.assertEqual([call.args for call in driver.axe.call_args_list], [
            ("key-combo", "--modifiers", "227", "--key", "4"),
            ("key-combo", "--modifiers", "227", "--key", "25"),
        ])
        with self.assertRaises(CommandError):
            driver.key(["shift", "shift", "a"])

    def test_positive_scroll_offsets_move_the_finger_up_and_left(self):
        driver = object.__new__(AxeSimulator)
        driver.viewport = (402, 874)
        driver.axe = Mock()
        driver.execute("pointer.scroll", {"x": 300, "y": 600, "dx": 1, "dy": 12})
        driver.axe.assert_called_once_with("draw", "300,600", "236,0", "--duration", "0.4")
