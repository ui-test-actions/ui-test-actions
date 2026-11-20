import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from contract import COMMANDS
from workflow import compile_workflow, read_mapping, source_workflow


def capabilities(target="linux"):
    return {"target": target, "commands": COMMANDS}


class WorkflowTest(unittest.TestCase):
    def test_compiles_declared_inputs_and_refuses_unsupported_steps_before_execution(self):
        workflow = {"version": 1, "inputs": ["value"], "steps": [
            {"action": {"command": "text.insert", "params": {"text": {"input": "value"}, "replace": True}}},
            {"action": {"command": "pointer.click", "params": {"x": 15, "y": 19}}},
        ]}
        value = "مرحبًا 🌍"
        compiled = compile_workflow(workflow, {"value": value}, capabilities())
        self.assertEqual(compiled[0]["action"]["params"]["text"], value)
        with self.assertRaisesRegex(ValueError, "declared inputs"):
            compile_workflow(workflow, {}, capabilities())
        with self.assertRaisesRegex(ValueError, "does not provide"):
            compile_workflow(workflow, {"value": value}, {
                "target": "linux", "commands": {"text.insert": COMMANDS["text.insert"]},
            })

    def test_visual_wait_references_only_an_earlier_recorded_frame(self):
        plan = {"version": 1, "steps": [
            {"action": {"command": "visual.sample"}, "save_as": "frame_1"},
            {"action": {"command": "visual.wait", "params": {"baseline": "frame_1", "condition": "changed"}}},
        ]}
        self.assertEqual(compile_workflow(plan, {}, capabilities()), plan["steps"])
        plan["steps"].reverse()
        with self.assertRaisesRegex(ValueError, "earlier saved baseline"):
            compile_workflow(plan, {}, capabilities())

    def test_recorded_coordinates_reject_a_different_target(self):
        source = {"version": 1, "target": "linux", "inputs": [], "events": [
            {"action": {"legacy": {"action": "click", "x": 15, "y": 19}}, "display": [1280, 800]},
        ]}
        plan = source_workflow(source)
        self.assertEqual(compile_workflow(plan, {}, capabilities()), plan["steps"])
        with self.assertRaisesRegex(ValueError, "original target"):
            compile_workflow(plan, {}, capabilities("macos"))

    def test_export_preserves_verified_transitions_and_finish_checks(self):
        check = {"element": {"selector": {"role": "text", "text": "Saved"}, "state": "present"}}
        source = {"version": 1, "status": "passed", "target": "linux", "steps": [
            {"outcome": "already_satisfied", "plan": {"summary": "skipped"}},
            {"outcome": "passed", "plan": {"summary": "save", "action": {"selector": {"name": "Save"}}, "expect": check}},
            {"outcome": "finished", "plan": {"summary": "done", "finish": True, "expect": check}},
        ]}
        workflow = source_workflow(source)
        self.assertEqual(workflow["steps"][-1], {"summary": "done", "expect": check})
        self.assertEqual(compile_workflow(workflow, {}, capabilities("windows")), workflow["steps"])
        source["status"] = "unexpected_state"
        with self.assertRaisesRegex(ValueError, "passed exploration report"):
            source_workflow(source)

    def test_expands_reusable_blocks_with_inputs(self):
        plan = {"version": 1, "inputs": ["shortcut"], "steps": [{"use": "save"}, {"use": "save"}],
                "blocks": {"save": [{"action": {"command": "keyboard.press", "params": {"keys": {"input": "shortcut"}}}}]}}
        stages = compile_workflow(plan, {"shortcut": ["ctrl", "s"]}, capabilities())
        self.assertEqual(len(stages), 2)
        self.assertEqual(stages[1]["action"]["params"]["keys"], ["ctrl", "s"])

    def test_rejects_excessive_document_nesting_before_binding(self):
        nested = []
        for _ in range(45):
            nested = [nested]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.yaml"
            path.write_text(json.dumps({"steps": nested}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nested values"):
                read_mapping(path)
