#!/usr/bin/env python3
"""Run agent-planned UI steps with deterministic before and after assertions."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryFile
import time

from agent import Client, ClientError
from contract import BOOLEAN, COORD, ELEMENT_FLAGS, SELECTOR, choice, integer, obj, string, validate
from contract import validate_operation


MUTATIONS = frozenset({
    "pointer.click", "pointer.move", "pointer.drag", "pointer.scroll", "pointer.pinch", "pointer.gesture",
    "keyboard.press", "text.insert", "device.rotate", "device.orientation"
})
ELEMENT = obj(("selector", "state"), selector=SELECTOR, state=choice("present", "absent"))
PIXEL = obj(("x", "y", "rgb"), x=COORD, y=COORD, tolerance=integer(0, 48),
            rgb={"type": "array", "minItems": 3, "maxItems": 3, "items": integer(0, 255)})
ASSERTION = obj(element=ELEMENT, pixel=PIXEL, timeout_ms=integer(100, 10000))
ACTION = obj(selector=SELECTOR, command=string(64), params={"type": "object"})
PROPOSAL = obj(("summary", "expect"), summary=string(300), before=ASSERTION, expect=ASSERTION,
               action=ACTION, finish=BOOLEAN)
NODE_FIELDS = ("role", "name", "text", "resource_id", "bounds", "visible", "enabled", "properties")
PNG = b"\x89PNG\r\n\x1a\n"


class ExplorationError(ValueError):
    pass


def validate_selector(selector):
    if "id" in selector or not (selector.get("role") or selector.get("name") or selector.get("text")
                                or selector.get("resource_id") or selector.get("text_contains")):
        raise ExplorationError("Use a semantic selector with a role, label, text or resource ID.")


def validate_assertion(expect, commands):
    kinds = set(expect) & {"element", "pixel"}
    if len(kinds) != 1:
        raise ExplorationError("Specify one deterministic expectation.")
    if "element" in kinds:
        if "element.find" not in commands or "element.wait" not in commands:
            raise ExplorationError("This driver needs a pixel expectation.")
        validate_selector(expect["element"]["selector"])


def validate_proposal(plan, commands):
    validate(plan, PROPOSAL, "plan")
    validate_assertion(plan["expect"], commands)
    if "before" in plan:
        validate_assertion(plan["before"], commands)
        if all(plan["before"].get(kind) == plan["expect"].get(kind) for kind in ("element", "pixel")):
            raise ExplorationError("The observed precondition and predicted outcome must differ.")
    if plan.get("finish"):
        if "action" in plan or "before" in plan:
            raise ExplorationError("A finishing assertion has no action or precondition.")
        return
    action = plan.get("action", {})
    if set(action) == {"selector"} and {"element.find", "element.click"} <= commands.keys():
        validate_selector(action["selector"])
    elif "command" in action and set(action) <= {"command", "params"} and action["command"] in MUTATIONS:
        validate_operation(action, commands)
    else:
        raise ExplorationError("Choose a unique semantic click or a supported UI action.")


class CommandPlanner:
    def __init__(self, argv, timeout, environment):
        self.argv = argv
        self.timeout = timeout
        self.environment = {
            name: os.environ[name] for name in
            ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", *environment)
            if name in os.environ
        }

    def __call__(self, request):
        with TemporaryFile() as output:
            try:
                result = subprocess.run(self.argv, input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
                                        stdout=output, stderr=subprocess.DEVNULL, env=self.environment,
                                        timeout=self.timeout, check=False)
            except subprocess.TimeoutExpired:
                raise ExplorationError("The planner exceeded its decision timeout.") from None
            if result.returncode:
                raise ExplorationError(f"The planner exited with status {result.returncode}.")
            output.seek(0)
            data = output.read(32769)
        if len(data) > 32768:
            raise ExplorationError("The planner response exceeds 32 KiB.")
        try:
            return json.loads(data)
        except (ValueError, RecursionError):
            raise ExplorationError("The planner must return one JSON object.") from None


class Exploration:
    def __init__(self, client, planner, output, objective, steps):
        self.client = client
        self.planner = planner
        self.output = output
        self.objective = objective
        self.steps = steps
        self.commands = {}
        self.report = {"version": 1, "objective": objective, "status": "running",
                       "steps": [], "states": {}, "transitions": []}

    def call(self, command, params):
        result = self.client.command(command, params)
        if not result.get("ok"):
            raise ClientError("The driver rejected a UI operation.", payload=result)
        return result["result"]

    def screenshot(self):
        image = self.client.fetch("/v1/screenshot")
        if not image.startswith(PNG):
            raise ExplorationError("The runner did not return a PNG screenshot.")
        return image

    def observe(self, label):
        image = self.screenshot()
        screenshot = f"{label}.png"
        (self.output / screenshot).write_bytes(image)
        tree = self.call("tree.snapshot", {"limit": 400}) if "tree.snapshot" in self.commands else None
        nodes = []
        if tree:
            for node in tree["nodes"]:
                if not node.get("visible"):
                    continue
                safe = {key: node[key] for key in NODE_FIELDS if key in node}
                properties = safe.get("properties", {})
                safe["properties"] = {key: properties[key] for key in ELEMENT_FLAGS["properties"] if key in properties}
                if properties.get("password"):
                    safe["name"] = safe["text"] = ""
                nodes.append(safe)
        semantic = [[node.get(key, "") for key in ("role", "name", "text", "resource_id", "enabled")]
                    for node in nodes]
        signature = json.dumps(semantic, ensure_ascii=False, sort_keys=True).encode() if semantic else image
        state = sha256(signature).hexdigest()[:20]
        record = self.report["states"].setdefault(state, {"visits": 0, "first": screenshot, "visible_nodes": len(nodes)})
        record["visits"] += 1
        observation = {"state": state, "screenshot": str((self.output / screenshot).resolve()),
                       "tree": nodes if tree is not None else None,
                       "tree_truncated": tree.get("truncated", False) if tree else False}
        (self.output / f"{label}.json").write_text(json.dumps(observation, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")
        return observation

    def check(self, expect, *, wait, require_complete=True):
        if "element" in expect:
            condition = expect["element"]
            if wait:
                self.call("element.wait", {**condition, "timeout_ms": expect.get("timeout_ms", 4000)})
                return True
            observation = self.call("element.find", {"selector": condition["selector"]})
            if (not observation["matched"] and (require_complete or condition["state"] == "absent") and
                    self.call("tree.snapshot", {}).get("truncated")):
                raise ExplorationError("A truncated tree cannot establish the required precondition.")
            return bool(observation["matched"]) == (condition["state"] == "present")

        try:
            from PIL import Image
        except ImportError:
            raise ExplorationError("Pixel assertions require Pillow on the agent's machine.") from None
        target = expect["pixel"]
        deadline = time.monotonic() + expect.get("timeout_ms", 4000) / 1000
        while True:
            with Image.open(BytesIO(self.screenshot())) as image:
                if not 0 <= target["x"] < image.width or not 0 <= target["y"] < image.height:
                    raise ExplorationError("The assertion pixel is outside the screenshot.")
                actual = image.convert("RGB").getpixel((target["x"], target["y"]))
            if all(abs(a - b) <= target.get("tolerance", 0) for a, b in zip(actual, target["rgb"])):
                return True
            if not wait or time.monotonic() >= deadline:
                return False
            time.sleep(.2)

    def act(self, parameters):
        if "selector" not in parameters:
            return self.call(parameters["command"], parameters.get("params", {}))
        selector = {**parameters["selector"], "visible": True, "enabled": True}
        seen = self.call("element.find", {"selector": selector})
        if seen["matched"] != 1:
            raise ExplorationError(f"The click selector resolved to {seen['matched']} actionable elements.")
        return self.call("element.click", {"id": seen["nodes"][0]["id"], "snapshot_id": seen["snapshot_id"]})

    def write_report(self):
        temporary = self.output / "report.tmp"
        temporary.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.output / "report.json")

    def run(self, app_id):
        self.output.mkdir(mode=0o700)
        stage = "setup"
        try:
            self.report["target"] = self.client.identify()["target"]
            self.commands = json.loads(self.client.fetch("/v2/capabilities"))["commands"]
            if app_id:
                validate_operation({"command": "app.launch", "params": {"id": app_id}}, self.commands)
                self.call("app.launch", {"id": app_id})
            current = self.observe("initial")
            for number in range(1, self.steps + 1):
                stage = "planner"
                previous = self.report["steps"][-1] if self.report["steps"] else None
                commands = {key: self.commands[key] for key in sorted(MUTATIONS.intersection(self.commands))}
                request = {"version": 1, "objective": self.objective, "target": self.report["target"],
                           "observation": current, "commands": commands, "remaining_decisions": self.steps - number + 1,
                           "semantic_assertions": "element.wait" in self.commands, "last_step": previous,
                           "proposal_schema": PROPOSAL}
                step = {"number": number, "before": current["state"]}
                self.report["steps"].append(step)
                plan = self.planner(request)
                validate_proposal(plan, self.commands)
                step["plan"] = plan
                if plan.get("finish"):
                    if not any(item.get("outcome") == "passed" for item in self.report["steps"]):
                        raise ExplorationError("A run needs a verified state transition before it can finish.")
                    stage = "final_assertion"
                    if not self.check(plan["expect"], wait=True):
                        raise ExplorationError("The final expectation was not satisfied.")
                    step["outcome"] = "finished"
                    self.report["status"] = "passed"
                    return self.report
                stage = "precondition"
                before = plan.get("before")
                if before and not self.check(before, wait=False):
                    step["outcome"] = "precondition_failed"
                    self.write_report()
                    continue
                if self.check(plan["expect"], wait=False, require_complete=not before):
                    step["outcome"] = "already_satisfied"
                    self.write_report()
                    continue
                stage = "action"
                self.act(plan["action"])
                stage = "assertion"
                if not self.check(plan["expect"], wait=True):
                    raise ExplorationError("The predicted UI state did not appear.")
                stage = "observation"
                current = self.observe(f"step-{number:03}")
                step.update(outcome="passed", after=current["state"])
                self.report["transitions"].append({"step": number, "from": step["before"], "to": step["after"]})
                self.write_report()
            self.report["status"] = "budget_exhausted"
        except (ClientError, OSError, ValueError, KeyError) as error:
            self.report["status"] = "unexpected_state" if stage in {"assertion", "final_assertion"} else "unable_to_execute"
            self.report["failure_stage"] = stage
            self.report["error"] = str(error)
            if isinstance(error, ClientError) and error.payload:
                detail = error.payload.get("error", {})
                if isinstance(detail, dict) and isinstance(detail.get("code"), str):
                    self.report["driver_error"] = detail["code"]
            try:
                self.observe("failure")
            except (ClientError, OSError, ValueError):
                pass
            if self.report["status"] == "unexpected_state":
                expectation = self.report["steps"][-1]["plan"]["expect"]
                try:
                    observed = self.check({**expectation, "timeout_ms": 1200}, wait=True)
                    self.report["recheck"] = "appeared_late" if observed else "still_unobserved"
                except ClientError as recheck_error:
                    self.report["recheck"] = "still_unobserved" if recheck_error.status == 408 else "unavailable"
                except (OSError, ValueError, KeyError):
                    self.report["recheck"] = "unavailable"
        finally:
            self.write_report()
        return self.report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--access-file", type=Path)
    parser.add_argument("--planner-command", required=True, type=Path, help="JSON array of executable and arguments")
    parser.add_argument("--planner-env", action="append", default=[], metavar="VARIABLE")
    parser.add_argument("--planner-timeout", type=int, default=30, choices=range(1, 301), metavar="1..300")
    parser.add_argument("--objective", required=True)
    parser.add_argument("--output", required=True, type=Path, help="New private evidence directory")
    parser.add_argument("--steps", type=int, default=12, choices=range(2, 51), metavar="2..50")
    parser.add_argument("--app-id", help="Launch this runner-allowlisted app before observing")
    args = parser.parse_args()
    try:
        argv = json.loads(args.planner_command.read_text(encoding="utf-8"))
        if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or "\0" in arg for arg in argv):
            raise ExplorationError("The planner command file must contain an executable and its arguments.")
        client = Client(json.loads(args.connection.read_text(encoding="utf-8")), args.token_file, args.access_file)
        planner = CommandPlanner(argv, args.planner_timeout, args.planner_env)
        report = Exploration(client, planner, args.output, args.objective, args.steps).run(args.app_id)
    except (ClientError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "unable_to_execute", "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "report": str(args.output / "report.json")}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
