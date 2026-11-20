"""Serve the live UI toolkit over local MCP stdio."""

import argparse
import base64
import json
from pathlib import Path
import re
import sys
from tempfile import mkdtemp

from agent import ClientError
from contract import BATCH_REQUEST, OPERATION_REQUEST, integer, obj, string, validate
from explore import ASSERTION
from ui_sdk import SessionGroup


VERSION = "2025-11-25"
SUPPORTED_VERSIONS = {VERSION, "2025-06-18", "2025-03-26"}
MAX_REQUEST = 256 * 1024
DEVICE = string(64, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
OBJECT = {"type": "object"}
ACTION_FIELDS = OPERATION_REQUEST["properties"]
BATCH_FIELDS = BATCH_REQUEST["properties"]

TOOLS = {
    "ui_sessions": ("List configured runner sessions and their availability.", obj()),
    "ui_capabilities": ("Read the live device's supported commands and argument schemas.", obj(("device",), device=DEVICE)),
    "ui_inspect": ("Observe the device's native accessibility tree.", obj(("device",), device=DEVICE, limit=integer(1, 1200))),
    "ui_screenshot": ("Capture the current UI as a PNG image.", obj(("device",), device=DEVICE)),
    "ui_action": ("Execute a typed action from ui_capabilities.", obj(("device", "command"), device=DEVICE, **ACTION_FIELDS)),
    "ui_batch": ("Execute up to twelve typed actions in order on one device.",
                 obj(("device", "steps"), device=DEVICE, **BATCH_FIELDS)),
    "ui_assert": ("Wait for one explicit element or pixel condition.",
                  obj(("device", "expect"), device=DEVICE, expect=ASSERTION)),
    "ui_workflow": ("Replay a tested workflow and retain local evidence.",
                    obj(("device", "workflow"), device=DEVICE, workflow=OBJECT, inputs=OBJECT)),
    "ui_coordinate": ("Run an asserted scenario across configured devices.",
                     obj(("scenario",), scenario=OBJECT, inputs=OBJECT)),
}


def tool_result(value, *, error=False, content=None):
    if content is None:
        content = [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]
    return {"content": content, "structuredContent": value, "isError": error}


class MCP:
    def __init__(self, sessions, output_root=None):
        self.sessions = sessions
        self.output_root = output_root
        self.phase = "new"

    def output(self):
        if self.output_root is not None:
            self.output_root.mkdir(mode=0o700, exist_ok=True)
        return Path(mkdtemp(prefix="ui-workflow-", dir=self.output_root)) / "result"

    def invoke(self, name, params):
        if not isinstance(name, str) or name not in TOOLS:
            return tool_result({"code": "unknown_tool", "message": "The requested UI tool does not exist."}, error=True)
        try:
            validate(params, TOOLS[name][1], "arguments")
            if name == "ui_sessions":
                return tool_result({"sessions": self.sessions.sessions()})
            if name == "ui_coordinate":
                output = self.output()
                report = self.sessions.coordinate(params["scenario"], output, inputs=params.get("inputs"))
                return tool_result({"report": report, "evidence": str(output)}, error=report["status"] != "passed")

            device = self.sessions.device(params["device"])
            if name == "ui_screenshot":
                image = device.screenshot()
                return tool_result({"device": params["device"], "bytes": len(image)},
                                   content=[{"type": "image", "mimeType": "image/png",
                                             "data": base64.b64encode(image).decode("ascii")}])
            if name == "ui_workflow":
                output = self.output()
                report = device.run(params["workflow"], output, inputs=params.get("inputs"))
                return tool_result({"report": report, "evidence": str(output)}, error=report["status"] != "passed")
            if name == "ui_assert":
                result = device.expect(params["expect"])
                return tool_result(result, error=not result["satisfied"])
            if name == "ui_capabilities":
                result = device.capabilities()
            elif name == "ui_inspect":
                result = device.inspect(params.get("limit", 200))
            elif name == "ui_action":
                result = device.action(params["command"], params.get("params"), request_id=params.get("request_id"))
            else:
                result = device.batch(params["steps"], request_id=params.get("request_id"))
            return tool_result(result, error=result.get("ok") is False)
        except ClientError as error:
            data = error.payload.get("error", {}) if isinstance(error.payload, dict) else {}
            code = data.get("code", "") if isinstance(data, dict) else ""
            if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
                code = "runner_unavailable" if not error.status else "runner_rejected"
            message = ("The session could not be reached." if not error.status else
                       f"The runner returned HTTP {error.status} ({code}).")
            return tool_result({"code": code, "http_status": error.status, "message": message}, error=True)
        except (ValueError, KeyError, TypeError, OSError, RecursionError):
            return tool_result({"code": "invalid_arguments", "message": "The UI tool could not use the supplied input."}, error=True)

    @staticmethod
    def error(request_id, code, msg):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": msg}}

    def request(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self.error(None, -32600, "Invalid request")
        method = message["method"]
        if "id" not in message:
            if method == "notifications/initialized" and self.phase == "initializing":
                self.phase = "ready"
            return None
        request_id = message["id"]
        params = message.get("params", {})
        if type(request_id) not in (int, str):
            return self.error(None, -32600, "Invalid request ID")
        if not isinstance(params, dict):
            return self.error(request_id, -32602, "Invalid request parameters")
        if method == "initialize" and self.phase == "new":
            version = params.get("protocolVersion")
            if not isinstance(version, str):
                return self.error(request_id, -32602, "A protocol version is required")
            self.phase = "initializing"
            result = {"protocolVersion": version if version in SUPPORTED_VERSIONS else VERSION,
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "ui-test-actions", "version": "1.0.0"}}
        elif method == "ping":
            result = {}
        elif self.phase != "ready":
            return self.error(request_id, -32002, "Initialize the MCP session first")
        elif method == "tools/list":
            if params.get("cursor") is not None:
                return self.error(request_id, -32602, "No additional tool page")
            result = {"tools": [{"name": name, "description": description, "inputSchema": schema}
                                for name, (description, schema) in TOOLS.items()]}
        elif method == "tools/call":
            result = self.invoke(params.get("name"), params.get("arguments", {}))
        else:
            return self.error(request_id, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def serve(self, source, sink):
        while line := source.readline(MAX_REQUEST + 1):
            try:
                if len(line) > MAX_REQUEST:
                    while line and not line.endswith(b"\n"):
                        line = source.readline(MAX_REQUEST + 1)
                    result = self.error(None, -32600, "Request exceeds the transport limit")
                else:
                    result = self.request(json.loads(line))
            except (ValueError, RecursionError):
                result = self.error(None, -32700, "Parse error")
            if result is not None:
                sink.write(json.dumps(result, ensure_ascii=False).encode("utf-8") + b"\n")
                sink.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    try:
        MCP(SessionGroup.open(args.sessions), args.output_root).serve(sys.stdin.buffer, sys.stdout.buffer)
    except (ClientError, OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
