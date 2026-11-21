"""Verify whether credentialed requests reach a synthetic loopback origin."""

from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import re
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tunnel import Tunnel, download_tunnel
from transports import RouteProbe


class Origin(BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.server.probe_body if self.path == self.server.probe_path else b"diagnostic-only"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def markers(body):
    indicators = ("access denied", "forbidden", "service token", "cloudflare access",
                  "cloudflare tunnel", "1033", "1010", "1020", "self-hosted", "diagnostic-only",
                  "security service", "browser integrity", "just a moment", "cloudflare ray id")
    return [item for item in indicators if item.encode() in body.lower()]


def request(url, workspace, access, *options):
    output = workspace / "response"
    config = "".join(f'header = {json.dumps(key + ": " + value)}\n' for key, value in access.items())
    status = subprocess.check_output(["curl", "--noproxy", "*", "--silent", "--max-time", "12",
        "--config", "-", "--output", str(output), "--write-out", "%{http_code}", *options, url],
        input=config.encode(), stderr=subprocess.DEVNULL, timeout=15).decode()
    return {"http": int(status), "markers": markers(output.read_bytes())}


def python_request(probe, url, headers):
    try:
        with probe.opener.open(Request(url, headers=headers), timeout=10) as response:
            return {"http": response.status, "markers": markers(response.read(32768))}
    except HTTPError as error:
        with error:
            return {"http": error.code, "markers": markers(error.read(32768)),
                    "edge_challenge": error.headers.get("cf-mitigated") == "challenge"}


def main():
    host = "uitest.abdelrahmanfahmy.dev"
    token = os.environ.pop("UI_TEST_TUNNEL_TOKEN")
    identifier = os.environ.pop("UI_TEST_ACCESS_CLIENT_ID")
    secret = os.environ.pop("UI_TEST_ACCESS_CLIENT_SECRET")
    expected_id = os.environ.pop('EXPECTED_ACCESS_ID_HASH', '')
    if not token or not all(re.fullmatch(r"[!-~]{1,4096}", value) for value in (identifier, secret)):
        raise RuntimeError("Missing or malformed credential material.")
    print(json.dumps({"standard_client_id_suffix": identifier.endswith(".access"),
                      "credentials_have_distinct_values": identifier != secret,
                      "configured_client_id_matches_policy_token": (sha256(identifier.encode()).hexdigest() == expected_id) if expected_id else None}))
    with tempfile.TemporaryDirectory() as directory, HTTPServer(("127.0.0.1", 8787), Origin) as server:
        work = Path(directory)
        server.probe_path = "/_ui_origin/" + secrets.token_hex(16)
        identity = secrets.token_hex(12)
        server.probe_body = identity.encode("ascii")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connector = Tunnel(download_tunnel(work), 8787, work, hostname=host, token=token)
        try:
            origin = connector.start(time.monotonic() + 85, lambda: False)
            valid = {"CF-Access-Client-Id": identifier, "CF-Access-Client-Secret": secret}
            invalid = {**valid, "CF-Access-Client-Secret": "invalid-acceptance-credential"}
            time.sleep(4)
            for path in ("/", "/v1/session", "/v2/capabilities", "/_ui_origin/" + secrets.token_hex(16)):
                for label, headers in (("anonymous", {}), ("configured", valid), ("invalid", invalid)):
                    result = request(origin + path, work, headers)
                    print(json.dumps({"path": path.rsplit("/", 1)[0] + "/…" if path.startswith("/_ui_origin/") else path,
                                      "request": label, **result}), flush=True)
            probe = RouteProbe(server.probe_path, identity, valid)
            print(json.dumps({"python_action_route_probe": probe(origin, 10), "observation": probe.observation}),
                  flush=True)
            url = origin + server.probe_path
            config = {**valid, "Cache-Control": "no-store"}
            default_agent = f"Python-urllib/{sys.version_info.major}.{sys.version_info.minor}"
            options = {"curl_h2": (), "curl_h1": ("--http1.1",),
                       "curl_python_agent": ("--http1.1", "--user-agent", default_agent)}
            for label, option in options.items():
                print(json.dumps({"comparison": label, **request(url, work, config, *option)}), flush=True)
            for label, fields in (("urllib_no_cache", valid), ("urllib_default", config),
                                  ("urllib_product_agent", {**config, "User-Agent": "ui-test-actions/2"})):
                print(json.dumps({"comparison": label, **python_request(probe, url, fields)}), flush=True)
        finally:
            connector.close()
            server.shutdown()


if __name__ == "__main__":
    main()
