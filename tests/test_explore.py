import json
from io import BytesIO
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from agent import ClientError
from contract import COMMANDS
from explore import CommandPlanner, Exploration, PNG


def expectation(name):
    return {"element": {"selector": {"role": "text", "name": name}, "state": "present"}}


class FixtureClient:
    def __init__(self, *, matching_controls=1, advance=True, truncated=False):
        self.controls = matching_controls
        self.advance = advance
        self.truncated = truncated
        self.state = "Draft"
        self.clicks = 0
        self.launches = []

    def identify(self):
        return {"target": "linux"}

    def fetch(self, path):
        if path == "/v1/screenshot":
            return PNG
        if path == "/v2/capabilities":
            commands = {name: COMMANDS[name] for name in (
                "element.find", "element.wait", "element.click", "tree.snapshot", "app.launch"
            )}
            return json.dumps({"commands": commands}).encode()
        raise AssertionError(path)

    def command(self, action, params):
        if action == "tree.snapshot":
            data = {"nodes": [
                {"id": "1", "role": "text", "name": self.state, "enabled": True, "visible": True},
                {"id": "2", "role": "textbox", "name": "secret", "text": "sensitive",
                 "visible": True, "properties": {"password": True, "value": "sensitive"}},
            ], "truncated": self.truncated}
        elif action in {"element.find", "element.wait"}:
            name = params["selector"]["name"]
            matches = ([{"id": str(i)} for i in range(self.controls)] if name == "Save"
                       else [{"id": "1"}] if name == self.state else [])
            if action == "element.wait" and not matches:
                raise ClientError("Timed out", 408, {"error": {"code": "condition_timeout"}})
            data = {"matched": len(matches), "nodes": matches, "snapshot_id": "fresh"}
        elif action == "element.click":
            self.clicks += 1
            if self.advance:
                self.state = "Saved"
            data = {}
        elif action == "app.launch":
            self.launches.append(params["id"])
            data = {}
        else:
            raise AssertionError(action)
        return {"ok": True, "result": data}


class ExplorationTest(unittest.TestCase):
    def run_plans(self, plans, client, *, app_id=None):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "private"
            seen = []
            proposals = iter(plans)

            def planner(request):
                seen.append(request)
                return next(proposals)

            result = Exploration(client, planner, output, "Save the fixture", len(plans)).run(app_id)
            self.assertEqual(json.loads((output / "report.json").read_text()), result)
            screenshots = {item.name for item in output.glob("*.png")}
            return result, seen, screenshots

    @staticmethod
    def save(expected="Saved"):
        return {"summary": "Save the draft", "action": {"selector": {"role": "button", "name": "Save"}},
                "expect": expectation(expected)}

    def test_uses_current_state_and_verifies_transition_and_finish(self):
        client = FixtureClient()
        finish = {"summary": "The document is saved", "finish": True, "expect": expectation("Saved")}
        result, observations, screenshots = self.run_plans([self.save(), finish], client, app_id="fixture")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(client.launches, ["fixture"])
        self.assertEqual(client.clicks, 1)
        self.assertNotEqual(result["transitions"][0]["from"], result["transitions"][0]["to"])
        self.assertEqual(observations[-1]["last_step"]["outcome"], "passed")
        self.assertNotIn("sensitive", json.dumps(observations))
        self.assertEqual(screenshots, {"initial.png", "step-001.png"})

    def test_already_true_expectation_never_dispatches_action(self):
        client = FixtureClient()
        result, _, _ = self.run_plans([self.save("Draft")], client)
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertEqual(result["steps"][0]["outcome"], "already_satisfied")
        self.assertEqual(client.clicks, 0)

    def test_ambiguous_target_is_not_treated_as_a_product_failure(self):
        client = FixtureClient(matching_controls=2)
        result, _, screenshot = self.run_plans([self.save()], client)
        self.assertEqual(result["status"], "unable_to_execute")
        self.assertEqual(result["failure_stage"], "action")
        self.assertEqual(client.clicks, 0)
        self.assertIn("failure.png", screenshot)

    def test_missing_expected_outcome_preserves_the_live_failure(self):
        client = FixtureClient(advance=False)
        result, _, screenshot = self.run_plans([self.save()], client)
        self.assertEqual(result["status"], "unexpected_state")
        self.assertEqual(result["driver_error"], "condition_timeout")
        self.assertEqual(result["recheck"], "still_unobserved")
        self.assertEqual(client.clicks, 1)
        self.assertIn("failure.png", screenshot)

    def test_rejects_a_plan_without_an_assertion_and_destructive_operations(self):
        client = FixtureClient()
        for invalid in ({"summary": "just click"},
                        {**self.save(), "action": {"command": "app.uninstall", "params": {"id": "fixture"}}}):
            with self.subTest(plan=invalid):
                result, _, _ = self.run_plans([invalid], client)
                self.assertEqual(result["failure_stage"], "planner")
        self.assertEqual(client.clicks, 0)

    def test_requires_an_observed_precondition_if_the_initial_tree_is_truncated(self):
        client = FixtureClient(truncated=True)
        unresolved, _, _ = self.run_plans([self.save()], client)
        self.assertEqual(unresolved["failure_stage"], "precondition")
        self.assertEqual(client.clicks, 0)

        plan = {**self.save(), "before": expectation("Draft")}
        finish = {"summary": "The document is saved", "finish": True, "expect": expectation("Saved")}
        result, _, _ = self.run_plans([plan, finish], client)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(client.clicks, 1)

    def test_passes_only_explicit_planner_credentials(self):
        with patch.dict("os.environ", {"GH_TOKEN": "runner-key", "MODEL_API_KEY": "provider-key"}, clear=True):
            planner = CommandPlanner(["planner"], 10, ["MODEL_API_KEY"])
        self.assertEqual(planner.environment, {"MODEL_API_KEY": "provider-key"})

    def test_pixel_assertion_checks_rgb_at_the_observed_location(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is optional for semantic-only clients")
        pixels = Image.new("RGB", (3, 3), (25, 43, 66))
        pixels.putpixel((1, 2), (23, 99, 59))
        data = BytesIO()
        pixels.save(data, "PNG")
        run = Exploration(None, None, None, "Observe a visual change", 2)
        run.screenshot = data.getvalue

        self.assertTrue(run.check({"pixel": {"x": 1, "y": 2, "rgb": [23, 98, 59], "tolerance": 1}}, wait=False))
        self.assertFalse(run.check({"pixel": {"x": 0, "y": 2, "rgb": [23, 99, 59]}}, wait=False))
