from base64 import b64encode
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import Mock

from contract import COMMANDS
from coordinate import capture_value, run_scenario
from explore import PNG


class Session:
    def __init__(self, identity, target, *, barrier=None, writable=True):
        self.identity = identity
        self.target = target
        self.barrier = barrier
        self.commands = {name: COMMANDS[name] for name in
                         (("clipboard.get", "clipboard.set") if writable else ("clipboard.get",))}
        self.clipboard = ""
        self.writes = 0

    def identify(self):
        return {"target": self.target, "id": self.identity}

    def fetch(self, path):
        if path == "/v2/capabilities":
            return json.dumps({"target": self.target, "commands": self.commands}).encode()
        if path == "/v1/screenshot":
            return PNG
        raise AssertionError(path)

    def command(self, command, params):
        if command == "clipboard.set":
            if self.barrier and not self.writes:
                self.barrier.wait(2)
            self.writes += 1
            self.clipboard = params["text"]
        elif command != "clipboard.get":
            raise AssertionError(command)
        return {"ok": True, "result": {"text": self.clipboard}}


def copy_text(name):
    return {"version": 1, "inputs": [name], "steps": [
        {"action": {"command": "clipboard.set", "params": {"text": {"input": name}}}},
    ]}


class CoordinatorTest(unittest.TestCase):
    def execute(self, scenario, clients, inputs):
        with TemporaryDirectory() as directory:
            report = run_scenario(scenario, clients, inputs, Path(directory) / "private")
            self.assertEqual(json.loads((Path(directory) / "private" / "report.json").read_text()), report)
            return report

    def test_runs_three_distinct_targets_in_parallel_and_shares_captured_values(self):
        barrier = Barrier(3)
        clients = {name: Session(name, target, barrier=barrier)
                   for name, target in (("primary", "android"), ("secondary", "ios"), ("tertiary", "windows"))}
        scenario = {"version": 1, "inputs": ["fixture"], "stages": [
            {"name": "Fan out", "devices": {
                name: {"workflow": copy_text("fixture"), "capture": {name + "_observed": {"kind": "clipboard_text"}}}
                for name in clients
            }, "equal": [["primary_observed", "secondary_observed"], ["primary_observed", "tertiary_observed"]]},
            {"name": "Consume prior state", "devices": {
                "secondary": {"workflow": copy_text("primary_observed"),
                              "capture": {"repeated": {"kind": "clipboard_text"}}}
            }, "equal": [["fixture", "repeated"]]},
        ]}
        report = self.execute(scenario, clients, {"fixture": "اختبار 🌍"})
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["stages"][1]["captured"], ["repeated"])
        self.assertEqual(clients["secondary"].clipboard, "اختبار 🌍")
        self.assertNotIn("اختبار", json.dumps(report, ensure_ascii=False))

    def test_rejects_duplicate_sessions(self):
        clients = {name: Session("same-session", "linux") for name in ("one", "two")}
        scenario = {"version": 1, "stages": [
            {"name": "Capture", "devices": {"one": {"capture": {"value": {"kind": "clipboard_text"}}}}},
        ]}
        report = self.execute(scenario, clients, {})
        self.assertEqual(report["status"], "failed")
        self.assertIn("different authenticated session", report["error"])

    def test_preflights_all_workflows_in_a_stage_before_sending_actions(self):
        clients = {"one": Session("a", "android"), "two": Session("b", "ios", writable=False)}
        scenario = {"version": 1, "inputs": ["fixture"], "stages": [
            {"name": "Unsupported peer", "devices": {name: {"workflow": copy_text("fixture")} for name in clients}},
        ]}
        report = self.execute(scenario, clients, {"fixture": "must not write"})
        self.assertEqual(report["status"], "failed")
        self.assertEqual(clients["one"].writes, 0)

    def test_stops_after_mismatch_and_runs_configured_cleanup(self):
        clients = {"one": Session("a", "android"), "two": Session("b", "ios")}
        scenario = {"version": 1, "inputs": ["fixture", "empty"], "stages": [
            {"name": "Mismatch", "devices": {"one": {"capture": {"actual": {"kind": "clipboard_text"}}}},
             "equal": [["fixture", "actual"]]},
            {"name": "Skip after failure", "devices": {"two": {"workflow": copy_text("fixture")}}},
        ], "cleanup": {"one": copy_text("empty")}}
        report = self.execute(scenario, clients, {"fixture": "expected", "empty": ""})
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(report["stages"]), 1)
        self.assertEqual(report["cleanup"]["one"]["status"], "passed")
        self.assertEqual(clients["two"].writes, 0)

    def test_file_capture_uses_bytes_and_checks_the_reported_length(self):
        ui = Mock()
        data = b"actual saved file contents"
        ui.call.return_value = {"base64": b64encode(data).decode(), "size": len(data)}
        self.assertEqual(capture_value(ui, "files.read", {"name": "output.bin"}), sha256(data).hexdigest())
        ui.call.return_value["size"] += 1
        with self.assertRaisesRegex(ValueError, "file length"):
            capture_value(ui, "files.read", {"name": "output.bin"})
