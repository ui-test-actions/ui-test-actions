"""Command-line entry point for named live runner sessions."""

import argparse
import json
from pathlib import Path
import sys

from agent import ClientError
from ui_sdk import SessionGroup
from workflow import read_mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", required=True, type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sessions")
    for name in ("capabilities", "inspect", "screenshot", "action", "batch", "assert", "workflow"):
        sub.add_parser(name).add_argument("device")
    commands = sub.choices
    commands["inspect"].add_argument("--limit", type=int, default=200)
    commands["screenshot"].add_argument("output", type=Path)
    commands["action"].add_argument("operation")
    commands["action"].add_argument("--params", type=Path)
    commands["batch"].add_argument("operations", type=Path)
    for name in ("action", "batch"):
        commands[name].add_argument("--request-id")
    commands["assert"].add_argument("expectation", type=Path)
    sub.add_parser("coordinate").add_argument("scenario", type=Path)
    commands["workflow"].add_argument("workflow", type=Path)
    for name in ("workflow", "coordinate"):
        commands[name].add_argument("--inputs", type=Path)
        commands[name].add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        group = SessionGroup.open(args.sessions)
        outcome = "passed"
        if args.command == "sessions":
            value = {"sessions": group.sessions()}
        elif args.command == "coordinate":
            value = group.coordinate(read_mapping(args.scenario), args.output,
                                     inputs=read_mapping(args.inputs) if args.inputs else {})
            outcome = value["status"]
        else:
            device = group.device(args.device)
            if args.command == "capabilities":
                value = device.capabilities()
            elif args.command == "inspect":
                value = device.inspect(args.limit)
            elif args.command == "screenshot":
                data = device.screenshot()
                with args.output.open("xb") as image:
                    image.write(data)
                value = {"saved": str(args.output)}
            elif args.command == "action":
                value = device.action(args.operation, read_mapping(args.params) if args.params else {},
                                      request_id=args.request_id)
            elif args.command == "batch":
                data = read_mapping(args.operations)
                value = device.batch(data["steps"], request_id=args.request_id)
            elif args.command == "assert":
                value = device.expect(read_mapping(args.expectation))
            else:
                value = device.run(read_mapping(args.workflow), args.output,
                                   inputs=read_mapping(args.inputs) if args.inputs else {})
                outcome = value["status"]
        print(json.dumps(value, ensure_ascii=False))
        return 1 if outcome != "passed" or value.get("ok") is False or value.get("satisfied") is False else 0
    except ClientError as error:
        print(json.dumps({"ok": False, "http_status": error.status, "error": (error.payload or {}).get("error")
                          or {"message": str(error)}}, ensure_ascii=False), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        print(json.dumps({"ok": False, "error": {"message": str(error)}}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
