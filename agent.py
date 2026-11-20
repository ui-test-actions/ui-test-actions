#!/usr/bin/env python3
"""Small standard-library client for an existing agent's host."""

import argparse
from http.client import HTTPException
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


class ClientError(Exception):
    pass


class Client:
    def __init__(self, connection, token_file, access_file=None):
        parsed = urlsplit(connection["url"])
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ClientError("Use an HTTPS origin from a trusted connection artifact.")
        self.origin = parsed.geturl().rstrip("/")
        self.session_id = connection.get("session_id")
        token = Path(token_file).read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ClientError("The private token file must contain one 64-digit hexadecimal token.")
        self.headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if access_file:
            access = json.loads(Path(access_file).read_text(encoding="utf-8"))
            self.headers.update({
                "CF-Access-Client-Id": access["client_id"], "CF-Access-Client-Secret": access["client_secret"],
            })
        self.opener = build_opener(NoRedirect)

    def fetch(self, path, body=None, retries=2):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        for attempt in range(retries + 1):
            try:
                request = Request(self.origin + path, data=payload, headers=self.headers)
                with self.opener.open(request, timeout=38) as response:
                    data = response.read(24 * 1024 * 1024 + 1)
                if len(data) > 24 * 1024 * 1024:
                    raise ClientError("The response exceeds the client download limit.")
                return data
            except HTTPError as error:
                raw = error.read(4096)
                try:
                    status = json.loads(raw).get("error", {})
                except (ValueError, AttributeError):
                    status = {}
                busy = error.code == 429 and isinstance(status, dict) and status.get("code") == "session_busy"
                upstream_unavailable = error.code in (502, 503, 504) and not (
                    isinstance(status, dict) and status.get("code")
                )
                if attempt < retries and (busy or upstream_unavailable):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                if isinstance(status, dict):
                    status = status.get("code", "http_error")
                else:
                    status = "http_error"
                raise ClientError(f"HTTP {error.code} ({status})") from None
            except (URLError, TimeoutError, HTTPException, ConnectionError):
                if attempt >= retries:
                    raise ClientError("The session could not be reached. Confirm the job is still running.") from None
                time.sleep(0.5 * (attempt + 1))

    def identify(self):
        data = json.loads(self.fetch("/v1/session"))
        if self.session_id and data["id"] != self.session_id:
            raise ClientError("The HTTPS origin returned a different session.")
        return data

    def command(self, name, params, request_id=None):
        return json.loads(self.fetch("/v2/action", {
            "request_id": request_id or uuid.uuid4().hex, "command": name, "params": params,
        }))

    def batch(self, steps, request_id=None):
        return json.loads(self.fetch("/v2/batch", {
            "request_id": request_id or uuid.uuid4().hex, "steps": steps,
        }))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connection", type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--access-file", type=Path, help="Optional private Cloudflare Access credential JSON")
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("capabilities")
    for name in ("screenshot", "recording"):
        reader = commands.add_parser(name)
        reader.add_argument("output", type=Path)
    action = commands.add_parser("action")
    action.add_argument("command")
    action.add_argument("--params-file", type=Path)
    action.add_argument("--request-id")
    batch = commands.add_parser("batch")
    batch.add_argument("steps_file", type=Path)
    batch.add_argument("--request-id")
    args = parser.parse_args()
    try:
        connection = json.loads(args.connection.read_text(encoding="utf-8"))
        client = Client(connection, args.token_file, args.access_file)
        client.identify()
        if args.operation == "capabilities":
            data = json.loads(client.fetch("/v2/capabilities"))
        elif args.operation in ("screenshot", "recording"):
            path = "/v1/screenshot" if args.operation == "screenshot" else "/v2/recording"
            image = client.fetch(path)
            expected = b"\x89PNG\r\n\x1a\n" if args.operation == "screenshot" else b"GIF8"
            if not image.startswith(expected):
                raise ClientError("The server returned an unexpected image format.")
            with args.output.open("xb") as stream:
                stream.write(image)
            data = {"saved": str(args.output)}
        elif args.operation == "action":
            params = json.loads(args.params_file.read_text(encoding="utf-8")) if args.params_file else {}
            data = client.command(args.command, params, args.request_id)
        else:
            data = client.batch(json.loads(args.steps_file.read_text(encoding="utf-8")), args.request_id)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except ClientError as error:
        parser.exit(1, f"{error}\n")
    except (ValueError, OSError, KeyError, TypeError):
        parser.exit(1, "Could not read the input or decode the server response.\n")


if __name__ == "__main__":
    main()
