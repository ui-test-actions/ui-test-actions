from pathlib import Path
import runpy
import unittest
from unittest.mock import Mock, call, patch


journey = runpy.run_path(str(Path(__file__).with_name("p2pkit-journey.py")))


class AndroidComposerTest(unittest.TestCase):
    def test_targets_the_message_labels_parent_instead_of_the_hotspot_editor(self):
        device = journey["Device"].__new__(journey["Device"])
        device.target, device.ocr = "android", None
        label = {"role": "text", "text": "Message", "parent_id": "composer"}
        send = {"text": "Broadcast (1)", "enabled": True,
                "bounds": {"x": 10, "y": 30, "width": 30, "height": 14}}
        device.command = Mock()
        device.find = Mock(side_effect=[("snapshot", label), (None, {}), (None, {}),
                                        (None, send), (None, {})])

        with patch("time.sleep"):
            device.message("Android hello ORANGE")

        matches_label = device.find.call_args_list[0].args[0]
        self.assertFalse(matches_label({"role": "textbox", "text": ""}))
        self.assertFalse(matches_label({"role": "text", "text": "SSID"}))
        self.assertTrue(matches_label(label))
        self.assertEqual(device.command.call_args_list, [
            call("element.click", {"snapshot_id": "snapshot", "id": "composer"}),
            call("text.insert", {"text": "Android hello ORANGE", "replace": True}),
            call("pointer.click", {"x": 25, "y": 37}),
        ])
        matches_sent = device.find.call_args_list[-1].args[0]
        self.assertFalse(matches_sent({"role": "textbox", "text": "Android hello ORANGE"}))
        self.assertTrue(matches_sent({"role": "text", "text": "me [broadcast]: Android hello ORANGE"}))
