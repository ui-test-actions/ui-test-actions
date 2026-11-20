#!/usr/bin/env python3
"""Export live recordings or exploration reports and replay their UI workflows."""

import argparse
import json
from pathlib import Path
import re
from struct import unpack
import sys

from agent import Client, ClientError
from contract import COORD, SELECTOR, choice, integer, obj, string, validate, validate_operation
from explore import ASSERTION, UI, validate_assertion, validate_selector
from interaction_trace import INPUT_LIMIT, RECORDABLE


NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
ACTION = obj(selector=SELECTOR, command=string(64), params={"type": "object"}, legacy={"type": "object"})
LEGACY_TEXT = obj(("action", "text"), action=choice("type"), text=string(256, 1, r"[ -~]+"))
LEGACY_CLICK = obj(("action", "x", "y"), action=choice("click"), x=COORD, y=COORD,
                   duration_ms=integer(100, 3000))
LEGACY_DRAG = obj(("action", "x", "y", "end_x", "end_y"), action=choice("swipe"), x=COORD, y=COORD,
                  end_x=COORD, end_y=COORD, duration_ms=integer(100, 3000))


def source_workflow(source):
    if source.get("command") == "trace.stop" and source.get("ok"):
        source = source["result"]
    if source.get("version") != 1:
        raise ValueError("The source must be an interaction recording or exploration report version 1.")
    if "events" in source:
        if not isinstance(source["events"], list) or any(not isinstance(item, dict) for item in source["events"]):
            raise ValueError("The recording must contain event objects.")
        if source.get("truncated") or any("failed" in item for item in source["events"]):
            raise ValueError("Resolve the failed or truncated recording before exporting it for replay.")
        return {"version": 1, "target": source["target"], "inputs": source["inputs"],
                "steps": source["events"]}
    if source.get("status") != "passed":
        raise ValueError("Export only a passed exploration report.")
    return {"version": 1, "target": source["target"], "inputs": [], "steps": [
        {key: value for key, value in entry["plan"].items() if key != "finish"}
        for entry in source["steps"] if entry.get("outcome") in {"passed", "finished"}
    ]}


def bind(value, inputs):
    if isinstance(value, dict):
        if set(value) == {"input"}:
            parameter = value["input"]
            if not isinstance(parameter, str) or parameter not in inputs:
                raise ValueError("A workflow reference needs a declared, supplied input.")
            return inputs[parameter]
        return {key: bind(item, inputs) for key, item in value.items()}
    if isinstance(value, list):
        return [bind(item, inputs) for item in value]
    return value


def compile_workflow(workflow, inputs, capabilities):
    if (not isinstance(workflow, dict) or workflow.get("version") != 1 or
            set(workflow) - {"version", "steps", "target", "inputs", "blocks"}):
        raise ValueError("Expected a workflow version 1 with steps.")
    names = workflow.get("inputs", [])
    if (not isinstance(names, list) or any(not isinstance(name, str) or not NAME.fullmatch(name) for name in names)
            or len(names) != len(set(names)) or not isinstance(inputs, dict) or set(inputs) != set(names)):
        raise ValueError("Supply exactly the workflow's declared inputs.")
    source = workflow.get("steps")
    if not isinstance(source, list) or not 1 <= len(source) <= INPUT_LIMIT:
        raise ValueError(f"A workflow requires 1–{INPUT_LIMIT} steps.")
    blocks = workflow.get("blocks", {})
    if (not isinstance(blocks, dict) or any(not isinstance(name, str) or not NAME.fullmatch(name) or
                                           not isinstance(items, list) or not items
                                           for name, items in blocks.items())):
        raise ValueError("Every reusable block needs a name and steps.")
    steps = []
    for item in source:
        if isinstance(item, dict) and set(item) == {"use"}:
            name = item["use"]
            if not isinstance(name, str) or name not in blocks:
                raise ValueError("A step references an unknown reusable block.")
            steps.extend(blocks[name])
        else:
            steps.append(item)
        if len(steps) > INPUT_LIMIT:
            raise ValueError(f"Reusable blocks expanded beyond {INPUT_LIMIT} steps.")
    steps = bind(steps, inputs)
    commands = capabilities["commands"]
    baselines = set()
    for step in steps:
        if not isinstance(step, dict) or set(step) - {"summary", "action", "before", "expect", "save_as", "display", "ms"}:
            raise ValueError("A workflow step contains an unknown field.")
        if "summary" in step:
            validate(step["summary"], string(300), "summary")
        if "ms" in step:
            validate(step["ms"], integer(0, 10800000), "recorded timestamp")
        if "display" in step:
            size = {"type": "array", "minItems": 2, "maxItems": 2, "items": integer(1, 16384)}
            validate(step["display"], size, "display")
        for field in ("before", "expect"):
            if field in step:
                validate(step[field], ASSERTION, field)
                validate_assertion(step[field], commands)
        action = step.get("action")
        if action is None:
            if "expect" not in step or "save_as" in step:
                raise ValueError("An assertion-only step requires an expectation.")
            continue
        validate(action, ACTION, "action")
        if set(action) == {"selector"}:
            if not {"element.find", "element.click"} <= commands.keys():
                raise ValueError("This session cannot replay a semantic click.")
            validate_selector(action["selector"])
        elif set(action) == {"legacy"}:
            legacy = action["legacy"]
            schemas = {"type": LEGACY_TEXT, "click": LEGACY_CLICK, "swipe": LEGACY_DRAG}
            kind = legacy.get("action")
            if not isinstance(kind, str) or kind not in schemas:
                raise ValueError("Unknown legacy interaction.")
            validate(legacy, schemas[kind], "legacy interaction")
            if workflow.get("target") != capabilities["target"]:
                raise ValueError("Legacy inputs require the original target.")
        elif "command" in action and set(action) <= {"command", "params"}:
            name, params = validate_operation(action, commands)
            if name not in RECORDABLE or name == "element.click":
                raise ValueError("This command cannot be replayed directly.")
            if name == "visual.wait" and params["baseline"] not in baselines:
                raise ValueError("A visual wait must reference an earlier saved baseline.")
        else:
            raise ValueError("Choose one replay action.")
        if "display" in step and workflow.get("target") not in (None, capabilities["target"]):
            raise ValueError("Recorded coordinates require the original target.")
        if "save_as" in step:
            label = step["save_as"]
            validate(label, string(64, 1, r"[A-Za-z][A-Za-z0-9_]*"), "baseline name")
            if action.get("command") != "visual.sample" or label in baselines:
                raise ValueError("A unique saved name can only label a visual sample.")
            if len(baselines) >= 16:
                raise ValueError("A workflow can retain up to 16 named visual baselines.")
            baselines.add(label)
    return steps


def replay(client, workflow, inputs, output, screenshots=False):
    output.mkdir(mode=0o700)
    ui = UI(client)
    report = {"version": 1, "status": "running", "steps": []}
    baselines = {}
    try:
        report["target"] = client.identify()["target"]
        capabilities = json.loads(client.fetch("/v2/capabilities"))
        steps = compile_workflow(workflow, inputs, capabilities)
        (output / "before.png").write_bytes(ui.screenshot())
        for number, step in enumerate(steps, start=1):
            result = {"step": number, "stage": "precondition"}
            action = step.get("action")
            if action:
                legacy = action.get("legacy")
                result["operation"] = f"legacy.{legacy['action']}" if legacy else action.get("command", "element.click")
            report["steps"].append(result)
            if "display" in step and list(unpack(">II", ui.screenshot()[16:24])) != step["display"]:
                raise ValueError("The current display size differs from the recorded size.")
            if "before" in step and not ui.check(step["before"], wait=True):
                raise ValueError("The replay precondition did not appear.")
            if action:
                result["stage"] = "action"
                if "legacy" in action:
                    response = json.loads(client.fetch("/v1/input", action["legacy"], retries=0))
                    if not response.get("ok"):
                        raise ClientError("The legacy operation was rejected.")
                else:
                    if action.get("command") == "visual.wait":
                        params = action["params"]
                        action = {**action, "params": {**params, "baseline": baselines[params["baseline"]]}}
                    observed = ui.act(action)
                    if "save_as" in step:
                        baselines[step["save_as"]] = observed["baseline"]
            if "expect" in step:
                result["stage"] = "assertion"
                if not ui.check(step["expect"], wait=True):
                    raise ValueError("The replay expectation did not appear.")
            result["stage"] = "complete"
            if screenshots:
                (output / f"step-{number:03}.png").write_bytes(ui.screenshot())
        (output / "after.png").write_bytes(ui.screenshot())
        report["status"] = "passed"
    except (ClientError, ValueError, OSError, KeyError) as error:
        report.update(status="diverged", error=str(error))
        if isinstance(error, ClientError) and error.payload and isinstance(error.payload.get("error"), dict):
            report["driver_error"] = error.payload["error"].get("code")
        try:
            (output / "failure.png").write_bytes(ui.screenshot())
        except (ClientError, ValueError, OSError):
            pass
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def read_mapping(path):
    with path.open("rb") as stream:
        data = stream.read(500001)
    if len(data) > 500000:
        raise ValueError("The workflow document exceeds its size limit.")
    try:
        value = json.loads(data)
    except json.JSONDecodeError:
        if path.suffix.lower() not in (".yaml", ".yml"):
            raise
        try:
            import yaml
        except ImportError:
            raise ValueError("Install PyYAML to read handwritten YAML. Exported JSON-compatible YAML works directly.") from None
        try:
            value = yaml.safe_load(data)
        except yaml.YAMLError:
            raise ValueError("Invalid YAML workflow.") from None
    if not isinstance(value, dict):
        raise ValueError("Expected an object.")
    stack = [(value, 0)]
    visited = 0
    while stack:
        item, depth = stack.pop()
        visited += 1
        if depth > 40 or visited > 40000:
            raise ValueError("The workflow document contains too many nested values.")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("Workflow object keys must be strings.")
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def connection_options(parser):
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--access-file", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--screenshots", action="store_true", help="Retain a screenshot after every step")


def run_options(args, workflow):
    client = Client(read_mapping(args.connection), args.token_file, args.access_file)
    report = replay(client, workflow, read_mapping(args.inputs) if args.inputs else {}, args.output, args.screenshots)
    print(json.dumps({"status": report["status"], "report": str(args.output / "report.json")}))
    return 0 if report["status"] == "passed" else 1


def run_exported(workflow):
    parser = argparse.ArgumentParser(description="Replay this exported UI workflow.")
    connection_options(parser)
    try:
        return run_options(parser.parse_args(), workflow)
    except (ClientError, OSError, ValueError, KeyError, RecursionError) as error:
        print(json.dumps({"status": "unable_to_execute", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    export = sub.add_parser("export")
    export.add_argument("source", type=Path)
    export.add_argument("destination", type=Path)
    run = sub.add_parser("run")
    run.add_argument("workflow", type=Path)
    connection_options(run)
    args = parser.parse_args()
    try:
        if args.mode == "run":
            return run_options(args, read_mapping(args.workflow))
        workflow = source_workflow(read_mapping(args.source))
        data = json.dumps(workflow, ensure_ascii=False, indent=2)
        suffix = args.destination.suffix.lower()
        if suffix == ".py":
            data = ("import json\nfrom workflow import run_exported\n\n"
                    f"WORKFLOW = json.loads({data!r})\n\n"
                    'if __name__ == "__main__":\n    raise SystemExit(run_exported(WORKFLOW))')
        elif suffix not in (".json", ".yaml", ".yml"):
            raise ValueError("Export to .json, .yaml or .py.")
        with args.destination.open("x", encoding="utf-8") as stream:
            stream.write(data + "\n")
        return 0
    except (ClientError, OSError, ValueError, KeyError, RecursionError) as error:
        print(json.dumps({"status": "unable_to_execute", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
