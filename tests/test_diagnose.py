import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from agent import ClientError
from diagnose import collect, issue_draft, reduced_replay, shape_tree
from diagnostic_sources import DiagnosticSources


class FailureEvidenceTest(TestCase):
    def test_events_expose_only_approved_names_and_metadata(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "app.jsonl").write_text(
                '{"event":"app.crashed","code":17,"level":"error","message":"secret"}\n'
                '{"event":"sensitive","message":"secret"}\n'
                '{"event":"app.crashed","code":false,"level":"secret"}\n'
            )
            source = DiagnosticSources('{"app":{"path":"app.jsonl","events":["app.crashed"]}}', root)
            self.assertEqual(source.execute("diagnostics.events", {"source": "app"})["events"],
                             [{"event": "app.crashed", "code": 17, "level": "error"}, {"event": "app.crashed"}])
            with self.assertRaises(ValueError):
                DiagnosticSources('{"app":{"path":"../secret","events":["app.crashed"]}}', root)

    def test_collects_an_offline_failure_without_connection_metadata(self):
        client = Mock()
        client.identify.side_effect = ClientError("unexpected secret", 530)
        with TemporaryDirectory() as temp:
            bundle = Path(temp) / "bundle"
            report = {"status": "diverged", "error": "private text", "steps": [{"step": 2, "stage": "assertion"}]}
            result = collect(client, bundle, report=report)
            self.assertEqual(result["unavailable"], {"session.json": "http_530"})
            self.assertEqual(result["failure"]["step"], 2)
            self.assertNotIn("secret", (bundle / "manifest.json").read_text())
            self.assertNotIn("private text", (bundle / "manifest.json").read_text())
            client.fetch.assert_not_called()

    def test_reduces_expanded_steps_and_sanitizes_a_draft(self):
        report = {"status": "diverged", "steps": [{"step": 2, "stage": "assertion", "operation": ["wrong format"]}],
                  "driver_error": "[broken link](https://example.test)"}
        step = {"expect": {"pixel": {"x": 1, "y": 1, "rgb": [0, 0, 0]}}}
        original = {"version": 1, "steps": [{"use": "repeat"}, step], "inputs": ["actual_text"],
                    "blocks": {"repeat": [step, step]}}
        reduced = reduced_replay(original, report)
        self.assertEqual(reduced["steps"], [step, step])
        self.assertEqual(reduced["inputs"], ["actual_text"])
        draft = issue_draft({"target": "<secret>", "failure": {
            "step": 2, "stage": "assertion", "operation": "pointer.click", "code": report["driver_error"],
        }})
        self.assertNotIn("secret", draft)
        self.assertNotIn("https", draft)
        self.assertIn("pointer.click", draft)

    def test_tree_omits_label_values(self):
        tree = {"nodes": [{"role": "textbox", "name": "secret", "text": "unicode", "visible": True,
                           "properties": {"password": "secret", "value": "sensitive"}}], "truncated": True}
        shape = shape_tree(tree)
        self.assertEqual(shape, {"truncated": True, "nodes": [{"role": "textbox", "visible": True}]})
        self.assertNotIn("secret", json.dumps(shape))
