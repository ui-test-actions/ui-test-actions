"""Verify whether credentialed requests reach a synthetic loopback origin."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tunnel import Tunnel, download_tunnel


class Origin(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "15")
        self.end_headers()
        self.wfile.write(b"diagnostic-only")

    def log_message(self, *_args):
        pass


def request(url, workspace, access):
    output = workspace / "response"
    config = "".join(f'header = {json.dumps(key + ": " + value)}\n' for key, value in access.items())
    status = subprocess.check_output(["curl", "--noproxy", "*", "--silent", "--max-time", "12",
        "--config", "-", "--output", str(output), "--write-out", "%{http_code}", url],
        input=config.encode(), stderr=subprocess.DEVNULL, timeout=15).decode()
    body = output.read_bytes().lower()
    indicators = ("access denied", "forbidden", "service token", "cloudflare access",
                  "cloudflare tunnel", "1033", "self-hosted", "diagnostic-only")
    return {"http": int(status), "markers": [item for item in indicators if item.encode() in body]}


def main():
    host = "uitest.abdelrahmanfahmy.dev"
    token = os.environ.pop("UI_TEST_TUNNEL_TOKEN")
    identifier = os.environ.pop("UI_TEST_ACCESS_CLIENT_ID")
    secret = os.environ.pop("UI_TEST_ACCESS_CLIENT_SECRET")
    if not token or not all(re.fullmatch(r"[!-~]{1,4096}", value) for value in (identifier, secret)):
        raise RuntimeError("Missing or malformed credential material.")
    print(json.dumps({"standard_client_id_suffix": identifier.endswith(".access"),
                      "credentials_have_distinct_values": identifier != secret}))
    with tempfile.TemporaryDirectory() as directory, HTTPServer(("127.0.0.1", 8787), Origin) as server:
        work = Path(directory)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connector = Tunnel(download_tunnel(work), 8787, work, hostname=host, token=token)
        try:
            origin = connector.start(time.monotonic() + 85, lambda: False)
            valid = {"CF-Access-Client-Id": identifier, "CF-Access-Client-Secret": secret}
            invalid = {**valid, "CF-Access-Client-Secret": "invalid-acceptance-credential"}
            for attempt in range(3):
                for label, headers in (("anonymous", {}), ("configured", valid), ("invalid", invalid)):
                    result = request(origin + "/v1/session", work, headers)
                    print(json.dumps({"attempt": attempt + 1, "request": label, **result}), flush=True)
                time.sleep(2)
        finally:
            connector.close()
            server.shutdown()


if __name__ == "__main__":
    main()
