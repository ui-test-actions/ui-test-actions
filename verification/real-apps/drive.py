"""External client for the pinned real-application verification workflows."""

import argparse
import http.client
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

from verify import EXPECTED, TITLE

MAX_RESPONSE_BYTES = 16 * 1024 * 1024
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


class Client:
    def __init__(self, connection: Path, token_file: Path):
        config = json.loads(connection.read_text(encoding="utf-8"))
        url = urlsplit(config["url"])
        if (url.scheme != "https" or url.username or url.password or not url.hostname or url.query
                or url.fragment or url.path not in ("", "/") or url.port not in (443, None)):
            raise ValueError("The connection artifact must contain a plain HTTPS origin on port 443")
        token = token_file.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ValueError("The token file must contain the 64-digit session token")
        self.hostname = url.hostname
        self.token = token
        self.target = config["target"]
        self.session_id = config["session_id"]

    def request(self, method: str, path: str, data=None):
        connection = http.client.HTTPSConnection(self.hostname, timeout=35)
        headers = {"Authorization": f"Bearer {self.token}"}
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise RuntimeError("The response exceeded 16 MiB")
            if response.status != 200:
                error_code = None
                if response.headers.get_content_type() == "application/json":
                    err = json.loads(payload)
                    if isinstance(err.get("error"), dict):
                        error_code = err["error"].get("code")
                raise RuntimeError(f"HTTP {response.status}" + (f" ({error_code})" if error_code else ""))
            return payload
        finally:
            connection.close()

    def verify_session(self):
        response = json.loads(self.request("GET", "/v1/session"))
        if response["id"] != self.session_id or response["target"] != self.target:
            raise RuntimeError("The live session does not match the connection artifact")
        return response

    def capabilities(self):
        return json.loads(self.request("GET", "/v2/capabilities"))

    def action(self, command: str, params: dict):
        envelope = {"command": command, "params": params, "request_id": uuid4().hex}
        response = json.loads(self.request("POST", "/v2/action", envelope))
        if response.get("ok") is not True:
            raise RuntimeError(f"{command} did not report success")
        return response["result"]

    def screenshot(self, output: Path):
        payload = self.request("GET", "/v1/screenshot")
        if not payload.startswith(PNG_HEADER):
            raise RuntimeError("The screenshot response was not a PNG")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)

    def require(self, *commands):
        available = self.capabilities()["commands"]
        missing = [name for name in commands if name not in available]
        if missing:
            raise RuntimeError("Required commands are unavailable: " + ", ".join(missing))

    def click(self, point):
        self.action("pointer.click", {"x": point[0], "y": point[1]})

    def insert(self, text):
        self.action("text.insert", {"text": text, "replace": True})


def edit_document(client, args):
    if client.target not in ("linux", "windows", "macos", "android"):
        raise RuntimeError("The document journey requires a desktop target or Android")
    desktop = client.target != "android"
    if not desktop and not args.save:
        raise RuntimeError("Provide Android save coordinates from the current screenshot")
    client.require("pointer.click", "text.insert", *(("keyboard.press", "clipboard.get", "clipboard.set") if desktop else ()))
    client.screenshot(args.evidence / "before.png")
    if desktop:
        client.action("clipboard.set", {"text": EXPECTED})
        if client.action("clipboard.get", {})["text"] != EXPECTED:
            raise RuntimeError("The Unicode clipboard round trip changed the text")
    client.click(args.editor)
    client.insert(EXPECTED)
    time.sleep(0.4)
    if desktop:
        modifier = "command" if client.target == "macos" else "ctrl"
        client.action("keyboard.press", {"keys": [modifier, "s"]})
    else:
        client.click(args.save)
    time.sleep(0.8)
    client.screenshot(args.evidence / "after.png")


def write_note(client, args):
    if client.target != "ios":
        raise RuntimeError("The note journey is for iOS")
    client.require("pointer.click", "text.insert")
    client.screenshot(args.evidence / "before.png")
    client.click(args.title)
    client.insert(TITLE)
    client.click(args.body)
    client.insert(EXPECTED)
    time.sleep(1)
    client.screenshot(args.evidence / "after.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    subcommands = parser.add_subparsers(dest="operation", required=True)
    subcommands.add_parser("capabilities")
    screenshot = subcommands.add_parser("screenshot")
    screenshot.add_argument("output", type=Path)
    action = subcommands.add_parser("action")
    action.add_argument("command")
    action.add_argument("params", type=json.loads, default={}, nargs="?")
    editor = subcommands.add_parser("edit-document")
    editor.add_argument("--editor", type=int, nargs=2, required=True, metavar=("X", "Y"))
    editor.add_argument("--save", type=int, nargs=2, metavar=("X", "Y"))
    editor.add_argument("--evidence", type=Path, required=True)
    note = subcommands.add_parser("write-note")
    note.add_argument("--title", type=int, nargs=2, required=True, metavar=("X", "Y"))
    note.add_argument("--body", type=int, nargs=2, required=True, metavar=("X", "Y"))
    note.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()

    client = Client(args.connection, args.token_file)
    client.verify_session()
    if args.operation == "capabilities":
        print(json.dumps(client.capabilities(), ensure_ascii=False, indent=2))
    elif args.operation == "screenshot":
        client.screenshot(args.output)
    elif args.operation == "action":
        print(json.dumps(client.action(args.command, args.params), ensure_ascii=False))
    elif args.operation == "edit-document":
        edit_document(client, args)
    elif args.operation == "write-note":
        write_note(client, args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, http.client.HTTPException) as error:
        sys.exit(str(error))
