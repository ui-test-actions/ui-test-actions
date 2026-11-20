"""Compare a same-runner Quick Tunnel probe and native curl on hosted images."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tunnel import Tunnel, download_tunnel


BODY = b"transport-probe"
work = Path(os.environ["RUNNER_TEMP"]) / "quick-provider-probe"
work.mkdir(exist_ok=True)


class Server(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args):
        pass


with ThreadingHTTPServer(("127.0.0.1", 0), Server) as server:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connector = Tunnel(download_tunnel(work), server.server_port, work)
    try:
        origin = connector.start(time.monotonic() + 105, lambda: False)
        (work / "origin").write_text(origin + "\n", encoding="ascii")
        target = origin + "/_ui_origin/canary"
        for _ in range(8):
            for proxy in (ProxyHandler({}), ProxyHandler()):
                try:
                    with build_opener(proxy).open(target, timeout=3) as response:
                        print("python", bool(proxy.proxies), response.status, response.read(80) == BODY, flush=True)
                except URLError as error:
                    print("python", bool(proxy.proxies), type(error).__name__, type(error.reason).__name__, str(error.reason)[:220], flush=True)
                except OSError as error:
                    print("python", bool(proxy.proxies), type(error).__name__, str(error)[:220], flush=True)
            for flag in ("--ipv4", "--ipv6"):
                curl = subprocess.run(["curl", flag, "--noproxy", "*", "--silent", "--show-error", "--max-time", "3",
                                       "--write-out", " %{http_code}", target], text=True, capture_output=True, timeout=5)
                print("curl", flag, curl.returncode, curl.stdout[:120], curl.stderr[:260], flush=True)
            time.sleep(3)
    finally:
        connector.close()
        server.shutdown()
