"""Collect a private failure bundle and produce a smaller replay or issue draft."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from agent import Client, ClientError
from contract import APP_ID, COMMANDS, ELEMENT_FLAGS, validate


ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_json(path, value):
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def failure_summary(report):
    if not report or report.get("status") != "diverged":
        return None
    recent = report.get("steps")
    failed = recent[-1] if isinstance(recent, list) and recent and isinstance(recent[-1], dict) else {}
    stages = {"precondition", "action", "assertion", "complete"}
    operation = failed.get("operation")
    code = report.get("driver_error")
    step = failed.get("step")
    return {"step": step if type(step) is int and 1 <= step <= 160 else None,
            "stage": failed["stage"] if isinstance(failed.get("stage"), str) and failed["stage"] in stages else "setup",
            "operation": operation if isinstance(operation, str) and (operation in COMMANDS or operation in
                         ("legacy.type", "legacy.click", "legacy.swipe")) else None,
            "code": code if type(code) is str and ERROR_CODE.fullmatch(code) else None}


def shape_tree(tree):
    nodes = []
    for node in tree["nodes"]:
        shape = {key: node[key] for key in ("role", "bounds", "visible", "enabled") if key in node}
        flags = {key: value for key, value in node.get("properties", {}).items()
                 if key in ELEMENT_FLAGS["properties"] and type(value) is bool}
        if flags:
            shape["properties"] = flags
        nodes.append(shape)
    return {"truncated": tree.get("truncated", False), "nodes": nodes}


def collect(client, destination, *, report=None, app_id=None, include_content=False, recording_seconds=0):
    if app_id is not None:
        validate(app_id, APP_ID, "app ID")
    if type(recording_seconds) is not int or not (recording_seconds == 0 or 2 <= recording_seconds <= 20):
        raise ValueError("Record an aftermath clip for 2–20 seconds or leave recordings disabled.")
    destination.mkdir(mode=0o700)
    failures = {}
    manifest = {"version": 1, "started_at": now(), "failure": failure_summary(report), "files": {}}

    def store(name, action, signature=None):
        try:
            data = action()
            path = destination / name
            if signature:
                if not data.startswith(signature) or len(data) > 24 * 1024 * 1024:
                    raise ValueError("Unexpected capture format.")
                path.write_bytes(data)
            else:
                write_json(path, data)
            manifest["files"][name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                       "captured_at": now()}
            return data
        except ClientError as error:
            failures[name] = f"http_{error.status}" if error.status else "connection_unavailable"
        except (KeyError, ValueError, OSError):
            failures[name] = "capture_unavailable"
        return None

    def command(name, params=None):
        reply = client.command(name, params or {})
        if not reply["ok"]:
            raise ValueError("Diagnostic command rejected.")
        return reply["result"]

    def identity():
        session = client.identify()
        return {"target": session["target"], "seconds_remaining": session["seconds_remaining"]}

    def capability_schema():
        data = json.loads(client.fetch("/v2/capabilities", retries=0))
        return {key: value for key, value in data.items() if key in
                {"api_version", "target", "commands", "screen", "limits"}}

    session = store("session.json", identity)
    if session:
        manifest["target"] = session["target"]
        store("failure.png", lambda: client.fetch("/v1/screenshot", retries=0), b"\x89PNG\r\n\x1a\n")
        capabilities = store("capabilities.json", capability_schema)
        commands = capabilities.get("commands", {}) if capabilities else {}
        if "tree.snapshot" in commands:
            store("tree.json", lambda: command("tree.snapshot", {"limit": 1200}) if include_content else
                  shape_tree(command("tree.snapshot", {"limit": 1200})))
        if "performance.observations" in commands:
            store("timing.json", lambda: command("performance.observations"))
        if app_id and "app.metrics" in commands:
            store("process.json", lambda: command("app.metrics", {"id": app_id}))
        if "network.profile.get" in commands:
            store("network.json", lambda: command("network.profile.get"))
        if "diagnostics.sources" in commands:
            sources = store("log-sources.json", lambda: command("diagnostics.sources"))
            for name in (sources or {}).get("sources", []):
                if re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", name):
                    store(f"log-{name}.json", lambda: command("diagnostics.events", {"source": name}))
        if recording_seconds and {"recording.start", "recording.stop"} <= commands.keys():
            def aftermath():
                command("recording.start", {"duration_seconds": recording_seconds})
                time.sleep(recording_seconds)
                result = command("recording.stop")
                return client.fetch("/v2/recording", retries=0) if result.get("download") == "/v2/recording" else b""

            store("aftermath.gif", aftermath, b"GIF8")
    manifest["unavailable"] = failures
    manifest["finished_at"] = now()
    write_json(destination / "manifest.json", manifest)
    return manifest


def reduced_replay(workflow, report):
    from workflow import expand_steps
    failure = failure_summary(report)
    if not failure or not failure["step"]:
        raise ValueError("The report has no failed executable step to reproduce.")
    steps = expand_steps(workflow)
    if failure["step"] > len(steps):
        raise ValueError("The failure does not match the workflow length.")
    prefix = steps[:failure["step"]]
    # Preserve CLI input compatibility without embedding any supplied value.
    return {key: workflow[key] for key in ("version", "target", "inputs") if key in workflow} | {"steps": prefix}


def issue_draft(manifest):
    failure = manifest.get("failure")
    if not isinstance(failure, dict):
        raise ValueError("A structured failure is required to draft an issue.")
    failure = failure_summary({"status": "diverged", "steps": [failure], "driver_error": failure.get("code")})
    target = manifest.get("target")
    if target not in ("linux", "windows", "macos", "android", "ios"):
        target = "unknown"
    fingerprint = hashlib.sha256(json.dumps([target, failure], sort_keys=True).encode()).hexdigest()[:16]
    stage = failure["stage"]
    return (f"## UI test failure on {target}\n\n"
            f"- Step {failure['step'] or 'setup'} · {stage}\n"
            f"- Operation `{failure['operation'] or 'unknown'}`\n"
            f"- Error `{failure['code'] or 'unclassified'}`\n"
            f"- Signature `{fingerprint}`\n\n"
            "Add the verified reproduction steps and sanitized evidence before filing.\n")


def main():
    from workflow import read_mapping
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("connection", type=Path)
    capture.add_argument("--token-file", required=True, type=Path)
    capture.add_argument("--access-file", type=Path)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--report", type=Path)
    capture.add_argument("--app-id")
    capture.add_argument("--include-tree-content", action="store_true")
    capture.add_argument("--aftermath-seconds", type=int, default=0)
    reduce = sub.add_parser("prefix")
    reduce.add_argument("workflow", type=Path)
    reduce.add_argument("report", type=Path)
    reduce.add_argument("output", type=Path)
    draft = sub.add_parser("issue-draft")
    draft.add_argument("manifest", type=Path)
    draft.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "capture":
            client = Client(read_mapping(args.connection), args.token_file, args.access_file)
            collect(client, args.output, report=read_mapping(args.report) if args.report else None,
                    app_id=args.app_id, include_content=args.include_tree_content,
                    recording_seconds=args.aftermath_seconds)
        elif args.mode == "prefix":
            write_json(args.output, reduced_replay(read_mapping(args.workflow), read_mapping(args.report)))
        else:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(issue_draft(read_mapping(args.manifest)))
    except (ClientError, OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
