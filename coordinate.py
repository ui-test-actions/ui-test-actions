#!/usr/bin/env python3
"""Run phased UI workflows against independent live authenticated devices."""

import argparse
from base64 import b64decode
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

from agent import Client, ClientError
from contract import FILE_NAME, SELECTOR, validate
from explore import UI, validate_selector
from workflow import NAME, bind, compile_workflow, read_mapping, replay


def load_devices(path):
    specs = read_mapping(path)
    if not 2 <= len(specs) <= 8 or any(not NAME.fullmatch(name) for name in specs):
        raise ValueError("Provide 2–8 named device configurations.")
    devices = {}
    for name, spec in specs.items():
        if (not isinstance(spec, dict) or set(spec) - {"connection", "token_file", "access_file"} or
                any(not isinstance(value, str) or not value for value in spec.values()) or
                not {"connection", "token_file"} <= spec.keys()):
            raise ValueError(f"Device {name} requires a connection artifact and private token file.")
        config = path.parent / spec["connection"]
        access = path.parent / spec["access_file"] if "access_file" in spec else None
        devices[name] = Client(read_mapping(config), path.parent / spec["token_file"], access)
    return devices


def validate_capture(capture):
    if not isinstance(capture, dict):
        raise ValueError("A capture must describe an observable value.")
    kind = capture.get("kind")
    if kind == "clipboard_text" and set(capture) == {"kind"}:
        return "clipboard.get"
    if kind == "file_sha256" and set(capture) == {"kind", "name"}:
        return "files.read"
    if kind == "element_text" and set(capture) == {"kind", "selector"}:
        return "element.find"
    raise ValueError("Use a clipboard, file digest, or semantic text capture.")


def validate_scenario(scenario, clients, initial):
    if scenario.get("version") != 1 or set(scenario) - {"version", "inputs", "stages", "cleanup"}:
        raise ValueError("Expected a version 1 multi-device scenario.")
    names = scenario.get("inputs", [])
    if (not isinstance(names, list) or any(not isinstance(name, str) or not NAME.fullmatch(name) for name in names)
            or set(names) != set(initial) or len(names) != len(set(names))):
        raise ValueError("Supply exactly the scenario's declared inputs.")
    stages = scenario.get("stages")
    if not isinstance(stages, list) or not 1 <= len(stages) <= 40:
        raise ValueError("A scenario needs 1–40 stages.")
    known = set(initial)
    for stage in stages:
        if (not isinstance(stage, dict) or set(stage) - {"name", "devices", "equal"} or
                not isinstance(stage.get("name"), str) or not stage["name"].strip() or len(stage["name"]) > 120):
            raise ValueError("Each stage needs a name and device operations.")
        lanes = stage.get("devices")
        if not isinstance(lanes, dict) or not lanes or set(lanes) - clients.keys():
            raise ValueError("Each stage must use named devices from this session group.")
        created = set()
        for lane in lanes.values():
            if (not isinstance(lane, dict) or not lane or set(lane) - {"workflow", "capture"} or
                    ("workflow" in lane and not isinstance(lane["workflow"], dict))):
                raise ValueError("A device stage needs a workflow, captures, or both.")
            declared = lane.get("workflow", {}).get("inputs", [])
            if (not isinstance(declared, list) or any(not isinstance(name, str) for name in declared)
                    or not set(declared) <= known):
                raise ValueError("A device workflow can use inputs from earlier successful stages.")
            captures = lane.get("capture", {})
            if not isinstance(captures, dict) or ("workflow" not in lane and not captures):
                raise ValueError("Captures are named bindings.")
            for name, capture in captures.items():
                if not isinstance(name, str) or not NAME.fullmatch(name) or name in known or name in created:
                    raise ValueError("A capture needs a new binding name unique to the scenario.")
                validate_capture(capture)
                created.add(name)
        known.update(created)
        checks = stage.get("equal", [])
        if (not isinstance(checks, list) or any(not isinstance(pair, list) or len(pair) != 2 or
                                               any(not isinstance(name, str) or name not in known for name in pair)
                                               for pair in checks)):
            raise ValueError("An equality check needs two available binding names.")
    cleanup = scenario.get("cleanup", {})
    if (not isinstance(cleanup, dict) or set(cleanup) - clients.keys() or
            any(not isinstance(flow, dict) for flow in cleanup.values())):
        raise ValueError("Cleanup must map known device names to workflows.")


def prepare_capture(spec, context):
    command = validate_capture(spec)
    if command == "clipboard.get":
        return command, {}
    if command == "files.read":
        name = bind(spec["name"], context)
        validate(name, FILE_NAME, "file name")
        return command, {"name": name}
    selector = bind(spec["selector"], context)
    validate(selector, SELECTOR, "selector")
    validate_selector(selector)
    return command, {"selector": {**selector, "visible": True}}


def capture_value(ui, command, params):
    result = ui.call(command, params)
    if command == "clipboard.get":
        return result["text"]
    if command == "files.read":
        data = b64decode(result["base64"], validate=True)
        if result["size"] != len(data):
            raise ValueError("The exchange file length did not match the response.")
        return sha256(data).hexdigest()
    if result["matched"] != 1:
        raise ValueError("A semantic text capture must resolve to one visible element.")
    return result["nodes"][0]["text"]


def stage_parallel(lanes, clients, context, capabilities, directory):
    inputs = {}
    captures = {}
    for name, lane in lanes.items():
        if "workflow" in lane:
            workflow = lane["workflow"]
            supplied = {key: context[key] for key in workflow.get("inputs", [])}
            compile_workflow(workflow, supplied, capabilities[name])
            inputs[name] = supplied
        captures[name] = {key: prepare_capture(spec, context) for key, spec in lane.get("capture", {}).items()}
        for command, _ in captures[name].values():
            if command not in capabilities[name]["commands"]:
                raise ValueError(f"Device {name} does not provide the requested observation.")

    directory.mkdir(mode=0o700)

    def work(name, lane):
        started = time.monotonic()
        result = {"status": "passed"}
        bindings = {}
        try:
            if "workflow" in lane:
                report = replay(clients[name], lane["workflow"], inputs[name], directory / name)
                result.update(status=report["status"], report=f"{directory.name}/{name}/report.json")
            if result["status"] == "passed":
                ui = UI(clients[name])
                bindings = {key: capture_value(ui, command, params)
                            for key, (command, params) in captures[name].items()}
        except (ClientError, OSError, ValueError, KeyError) as error:
            result.update(status="failed", error=str(error))
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        return result, bindings

    with ThreadPoolExecutor(max_workers=len(lanes)) as pool:
        pending = {name: pool.submit(work, name, lane) for name, lane in lanes.items()}
        results = {name: future.result() for name, future in pending.items()}
    return ({name: result for name, (result, _) in results.items()},
            {key: value for _, outputs in results.values() for key, value in outputs.items()})


def run_scenario(scenario, clients, initial, output):
    validate_scenario(scenario, clients, initial)
    output.mkdir(mode=0o700)
    report = {"version": 1, "status": "running", "devices": {}, "stages": []}
    context = dict(initial)
    capabilities = {}
    acquired = False
    try:
        identities = {name: client.identify() for name, client in clients.items()}
        if len({identity["id"] for identity in identities.values()}) != len(identities):
            raise ValueError("Every device must refer to a different authenticated session.")
        report["devices"] = {name: identity["target"] for name, identity in identities.items()}
        capabilities = {name: json.loads(client.fetch("/v2/capabilities")) for name, client in clients.items()}
        acquired = True
        for number, stage in enumerate(scenario["stages"], 1):
            entry = {"name": stage["name"], "status": "failed"}
            report["stages"].append(entry)
            results, captured = stage_parallel(stage["devices"], clients, context, capabilities, output / f"stage-{number:02}")
            entry["devices"] = results
            if any(result["status"] != "passed" for result in results.values()):
                raise ValueError("At least one device action failed. Further stages were skipped.")
            candidate = {**context, **captured}
            checks = [{"bindings": pair, "equal": candidate[pair[0]] == candidate[pair[1]]}
                      for pair in stage.get("equal", [])]
            entry["checks"] = checks
            if any(not check["equal"] for check in checks):
                raise ValueError("A cross-device equality assertion failed.")
            context = candidate
            entry.update(status="passed", captured=sorted(captured))
            persist_report(output, report)
        report["status"] = "passed"
    except (ClientError, OSError, ValueError, KeyError) as error:
        report.update(status="failed", error=str(error))
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        raise
    finally:
        if acquired and scenario.get("cleanup"):
            lanes = {name: {"workflow": flow} for name, flow in scenario["cleanup"].items()}
            try:
                cleanup, _ = stage_parallel(lanes, clients, context, capabilities, output / "cleanup")
                report["cleanup"] = cleanup
                if any(result["status"] != "passed" for result in cleanup.values()):
                    report["status"] = "failed"
            except (ClientError, OSError, ValueError, KeyError) as error:
                report.update(status="failed", cleanup_error=str(error))
        persist_report(output, report)
    return report


def persist_report(output, report):
    temporary = output / "report.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output / "report.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--devices", type=Path, required=True)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        devices = load_devices(args.devices)
        report = run_scenario(read_mapping(args.scenario), devices, read_mapping(args.inputs) if args.inputs else {},
                              args.output)
    except (ClientError, ValueError, OSError, KeyError, RecursionError) as error:
        print(json.dumps({"status": "unable_to_execute", "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "report": str(args.output / "report.json")}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
