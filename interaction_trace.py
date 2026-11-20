"""Bounded, authenticated session-local recording of UI commands."""

import json
import time

from contract import CommandError


INPUT_LIMIT = 160
BYTE_LIMIT = 240000
RECORDABLE = frozenset({
    "pointer.move", "pointer.click", "pointer.drag", "pointer.scroll", "pointer.pinch", "pointer.gesture",
    "keyboard.press", "text.insert", "clipboard.set", "element.click", "element.assert", "element.wait",
    "visual.sample", "visual.wait", "app.launch", "app.close", "app.restart", "device.rotate", "device.orientation",
})
PRIVATE_FIELDS = frozenset({"text", "text_contains"})


class InteractionTrace:
    def __init__(self, session):
        self.session = session
        self.started = None

    def start(self, capture_text=False):
        if self.started is not None:
            raise CommandError("trace_active", "Stop the active interaction recording first.", 409)
        self.started = time.monotonic()
        self.capture_text = capture_text
        self.events = []
        self.parameters = []
        self.size = 0
        self.truncated = False
        self.baselines = {}
        return {"recording": True, "capture_text": capture_text, "max_events": INPUT_LIMIT}

    def stop(self):
        if self.started is None:
            raise CommandError("trace_inactive", "Start an interaction recording first.", 409)
        self.started = None
        return {"version": 1, "target": self.session.target, "events": self.events,
                "inputs": self.parameters, "truncated": self.truncated}

    def append(self, event):
        elapsed = round(1000 * (time.monotonic() - self.started))
        pending = []

        def redact(item):
            if isinstance(item, dict):
                out = {}
                for key, value in item.items():
                    if not self.capture_text and key in PRIVATE_FIELDS and isinstance(value, str):
                        parameter = f"text_{len(self.parameters) + len(pending) + 1}"
                        pending.append(parameter)
                        out[key] = {"input": parameter}
                    else:
                        out[key] = redact(value)
                return out
            if isinstance(item, list):
                return [redact(value) for value in item]
            return item

        entry = {"ms": elapsed, **redact(event)}
        size = len(json.dumps(entry, ensure_ascii=True).encode("utf-8"))
        if len(self.events) >= INPUT_LIMIT or self.size + size > BYTE_LIMIT:
            self.truncated = True
            return
        self.events.append(entry)
        self.parameters.extend(pending)
        self.size += size

    def command(self, name, params, result=None, error=None):
        if self.started is None or self.truncated or name not in RECORDABLE:
            return
        if error:
            self.append({"failed": {"command": name, "code": error}})
            return
        if name == "element.click":
            return
        entry = {"command": name, "params": params}
        event = {}
        if name.startswith("pointer."):
            event["display"] = list(self.session.size)
        if name == "visual.sample":
            baseline = f"frame_{len(self.baselines) + 1}"
            self.baselines[result["baseline"]] = baseline
            event["save_as"] = baseline
        if name == "visual.wait":
            params = dict(params)
            baseline = self.baselines.get(params["baseline"])
            if baseline is None:
                self.append({"failed": {"command": name, "code": "baseline_outside_trace"}})
                return
            params["baseline"] = baseline
            entry["params"] = params
        self.append({"action": entry, **event})

    def click(self, node, nodes, x, y):
        if self.started is None or self.truncated:
            return
        limits = {"role": 256, "resource_id": 256, "name": 512}
        selector = {key: node[key] for key in limits
                    if isinstance(node.get(key), str) and 0 < len(node[key]) <= limits[key]}
        if node.get("properties", {}).get("password"):
            selector.pop("name", None)
        if (selector and any(key in selector for key in ("resource_id", "name"))
                and sum(all(node.get(key) == value for key, value in selector.items()) and
                        node.get("visible") is not False and node.get("enabled") is not False
                        for node in nodes) == 1):
            self.append({"action": {"selector": selector}})
        else:
            self.command("pointer.click", {"x": x, "y": y}, {})

    def legacy(self, params):
        if self.started is None or self.truncated:
            return
        event = {"action": {"legacy": params}}
        if params["action"] != "type":
            event["display"] = list(self.session.size)
        self.append(event)
