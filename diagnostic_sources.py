"""Read bounded, explicitly allowlisted events from workflow-owned test logs."""

import json
from pathlib import Path
import re
import stat

from contract import CommandError


NAME = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
TAIL_BYTES = 65536
EVENT_LIMIT = 80


class DiagnosticSources:
    def __init__(self, configuration, root):
        self.root = root.resolve(strict=True)
        mapping = json.loads(configuration)
        if type(mapping) is not dict or len(mapping) > 8:
            raise ValueError("Configure up to eight named diagnostic log sources.")
        self.sources = {}
        for name, definition in mapping.items():
            if (not NAME.fullmatch(name) or type(definition) is not dict or set(definition) != {"path", "events"} or
                    type(definition["path"]) is not str or not definition["path"] or
                    type(definition["events"]) is not list or not 1 <= len(definition["events"]) <= 50 or
                    any(type(event) is not str or not NAME.fullmatch(event) for event in definition["events"])):
                raise ValueError("Diagnostic logs require a path and a bounded list of event names.")
            path = (self.root / definition["path"]).resolve()
            if path == self.root or not path.is_relative_to(self.root):
                raise ValueError("Diagnostic log files must be inside RUNNER_TEMP.")
            self.sources[name] = (path, frozenset(definition["events"]))

    def execute(self, name, params):
        if name == "diagnostics.sources":
            return {"sources": sorted(self.sources)}
        source = params["source"]
        if source not in self.sources:
            raise CommandError("target_not_found", "This diagnostic log was not enabled by the workflow.", 404)
        path, enabled = self.sources[source]
        try:
            if path.resolve(strict=True) != path:
                raise OSError("Log path changed.")
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError("Log is not a single regular file.")
            with path.open("rb") as log:
                start = max(0, info.st_size - TAIL_BYTES)
                log.seek(start)
                content = log.read(TAIL_BYTES)
        except OSError as error:
            raise CommandError("diagnostics_unavailable", "The selected diagnostic log is unavailable.", 404) from error
        lines = content.splitlines()
        if start and lines:
            lines = lines[1:]
        records = []
        for entry in lines:
            try:
                event = json.loads(entry)
            except (ValueError, RecursionError):
                continue
            if type(event) is not dict or type(event.get("event")) is not str or event["event"] not in enabled:
                continue
            result = {"event": event["event"]}
            if type(event.get("epoch_ms")) is int and 946684800000 <= event["epoch_ms"] <= 4102444800000:
                result["epoch_ms"] = event["epoch_ms"]
            if type(event.get("code")) is int and -65535 <= event["code"] <= 65535:
                result["code"] = event["code"]
            if event.get("level") in ("debug", "info", "warning", "error"):
                result["level"] = event["level"]
            records.append(result)
        return {"source": source, "events": records[-EVENT_LIMIT:], "truncated": bool(start) or len(records) > EVENT_LIMIT}
