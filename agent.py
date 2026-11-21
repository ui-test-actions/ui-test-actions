#!/usr/bin/env python3
"""Small standard-library client for an existing agent's host."""

import argparse
from http.client import HTTPException, HTTPResponse, IncompleteRead
from ipaddress import IPv4Address
import json
from pathlib import Path
import re
import ssl
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
import uuid


HTTP_USER_AGENT = "ui-test-actions/2"
MAX_DOWNLOAD = 24 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


class ClientError(Exception):
    def __init__(self, message, status=None, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class Client:
    def __init__(self, connection, token_file, access_file=None):
        self.origin, self.opener = open_origin(connection)
        self.session_id = connection.get("session_id")
        token = Path(token_file).read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ClientError("The private token file must contain one 64-digit hexadecimal token.")
        self.headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if connection.get("transport") == "cloudflare-named" or access_file:
            self.headers["User-Agent"] = HTTP_USER_AGENT
        if self.session_id:
            self.headers["X-UI-Session-ID"] = self.session_id
        if connection.get("cloudflare_access") and not access_file:
            raise ClientError("This session requires a private Cloudflare Access credentials file.")
        if access_file:
            if connection.get("transport") not in (None, "cloudflare-named"):
                raise ClientError("Only a named tunnel can use Cloudflare Access credentials.")
            access = json.loads(Path(access_file).read_text(encoding="utf-8"))
            if not isinstance(access, dict) or not all(
                isinstance(access.get(key), str) and re.fullmatch(r"[!-~]{1,4096}", access[key])
                for key in ("client_id", "client_secret")
            ):
                raise ClientError("The private Access file must contain a valid credential pair.")
            self.headers.update({
                "CF-Access-Client-Id": access["client_id"], "CF-Access-Client-Secret": access["client_secret"],
            })

    def fetch(self, path, body=None, retries=2):
        if not path.startswith("/") or path.startswith("//") or "\\" in path or not path.isprintable():
            raise ClientError("Expected an absolute path on the existing session origin.")
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        for attempt in range(retries + 1):
            try:
                request = Request(self.origin + path, data=payload, headers=self.headers)
                with self.opener.open(request, timeout=38) as response:
                    data = response.read(MAX_DOWNLOAD + 1)
                    if len(data) <= MAX_DOWNLOAD and isinstance(response, HTTPResponse) and response.length:
                        raise IncompleteRead(b"", response.length)
                if len(data) > MAX_DOWNLOAD:
                    raise ClientError("The response exceeds the client download limit.")
                return data
            except HTTPError as error:
                try:
                    with error:
                        raw = error.read(512 * 1024)
                except (OSError, HTTPException):
                    raw = b""
                try:
                    error_payload = json.loads(raw)
                    if not isinstance(error_payload, dict):
                        error_payload = {}
                except ValueError:
                    error_payload = {}
                status = error_payload.get("error", {})
                busy = error.code == 429 and (
                    isinstance(status, dict) and status.get("code") == "session_busy"
                    or body is None and status == "The session is busy"
                )
                upstream_unavailable = error.code in (502, 503, 504) and not (
                    isinstance(status, dict) and status.get("code")
                )
                if attempt < retries and (busy or body is None and upstream_unavailable):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                if isinstance(status, dict):
                    status = status.get("code", "http_error")
                else:
                    status = "http_error"
                if body is not None and upstream_unavailable:
                    raise uncertain_action(error.code, body) from None
                raise ClientError(f"HTTP {error.code} ({status})", error.code, error_payload) from None
            except (URLError, TimeoutError, HTTPException, ConnectionError):
                if body is not None:
                    raise uncertain_action(body=body) from None
                if attempt >= retries:
                    raise ClientError("The session could not be reached. Confirm the job is still running.") from None
                time.sleep(0.5 * (attempt + 1))

    def identify(self):
        data = json.loads(self.fetch("/v1/session"))
        if self.session_id and data["id"] != self.session_id:
            raise ClientError("The endpoint returned a different session.")
        return data

    def command(self, name, params, request_id=None):
        return self.action_result("/v2/action", {
            "request_id": request_id or uuid.uuid4().hex, "command": name, "params": params,
        })

    def batch(self, steps, request_id=None):
        return self.action_result("/v2/batch", {
            "request_id": request_id or uuid.uuid4().hex, "steps": steps,
        })

    def action_result(self, path, body):
        data = self.fetch(path, body)
        try:
            result = json.loads(data)
        except (ValueError, RecursionError):
            raise uncertain_action(body=body) from None
        if (not isinstance(result, dict) or type(result.get("ok")) is not bool
                or result.get("request_id") != body["request_id"]):
            raise uncertain_action(body=body)
        return result


def open_origin(connection):
    kind = connection.get("transport")
    try:
        url = connection["url"]
        parsed = urlsplit(url)
        port = parsed.port
        if (not re.fullmatch(r"[!-~]+", url) or not parsed.hostname or "@" in parsed.netloc
                or "\\" in url or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError()
        if kind == "local" and parsed.scheme == "http" and port and parsed.netloc == f"127.0.0.1:{port}":
            return parsed.geturl().rstrip("/"), build_opener(NoRedirect(), ProxyHandler({}))
        if parsed.scheme == "https" and kind == "private" and port:
            if parsed.netloc != f"{IPv4Address(parsed.hostname)}:{port}":
                raise ValueError()
            certificate = connection["ca_pem"]
            if not re.fullmatch(r"-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*", certificate):
                raise ValueError()
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_verify_locations(cadata=certificate)
            return parsed.geturl().rstrip("/"), build_opener(NoRedirect(), ProxyHandler({}), HTTPSHandler(context=context))
        if parsed.scheme == "https" and kind in (None, "cloudflare-quick", "cloudflare-named"):
            return parsed.geturl().rstrip("/"), build_opener(NoRedirect())
    except (ValueError, KeyError, TypeError, ssl.SSLError):
        pass
    raise ClientError("Invalid transport or origin. Use the connection artifact from your trusted run.")


def uncertain_action(status=None, body=None):
    message = "The action response was lost. Inspect the live UI before deciding whether to retry."
    payload = {"ok": False, "error": {"code": "action_outcome_unknown", "message": message}}
    if isinstance(body, dict) and isinstance(body.get("request_id"), str):
        payload["request_id"] = body["request_id"]
    return ClientError(message, status, payload)


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
        result = error.payload or {"error": {"message": str(error)}}
        print(json.dumps({"http_status": error.status, **result}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError, KeyError, TypeError):
        parser.exit(1, "Could not read the input or decode the server response.\n")


if __name__ == "__main__":
    main()
