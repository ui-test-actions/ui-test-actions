"""Start the runner-owned Cloudflare connector without forwarding its credential."""

import os
from pathlib import Path
import re
import subprocess
import time


QUICK_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
HOSTNAME = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


class Tunnel:
    def __init__(self, binary, port, work, hostname="", token=""):
        self.hostname = hostname.lower()
        self.token_file = None
        self.work = work
        self.log = work / "cloudflared.log"
        self.config = work / "cloudflared.yml"
        self.config.write_text("{}\n", encoding="utf-8")
        self.command = [
            str(binary), "--config", str(self.config), "tunnel", "--no-autoupdate",
            "--protocol", "http2", "--loglevel", "info",
        ]
        if hostname or token:
            if not HOSTNAME.fullmatch(self.hostname) or not token or port == 0:
                raise ValueError("Named tunnels require a hostname, a fixed origin port, and a secret token.")
            self.token_file = work / "connector.token"
            fd = os.open(self.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(token)
            self.command.extend(("run", "--token-file", str(self.token_file)))
        else:
            self.command.extend(("--url", f"http://127.0.0.1:{port}"))
        # Do not honor tunnel overrides from the workflow's environment.
        self.env = {name: value for name, value in os.environ.items() if not name.upper().startswith("TUNNEL_")}
        self.process = None

    def start(self, deadline, cancelled):
        attempt = 0
        while time.monotonic() < deadline and not cancelled():
            attempt += 1
            with self.log.open("wb") as output:
                self.process = subprocess.Popen(self.command, env=self.env, stdout=output, stderr=subprocess.STDOUT)
            attempt_deadline = min(deadline, time.monotonic() + 37)
            while time.monotonic() < attempt_deadline and not cancelled() and self.process.poll() is None:
                tail = self.read_tail()
                match = QUICK_URL.search(tail)
                if (self.hostname or match) and "Registered tunnel connection" in tail:
                    return "https://" + self.hostname if self.hostname else match.group()
                time.sleep(0.5)
            self.stop_process()
            if attempt >= 3:
                break
        if cancelled():
            raise RuntimeError("Session startup was cancelled.")
        raise RuntimeError(f"Cloudflare connector did not register after {attempt} attempt(s). Check runner egress and tunnel configuration.")

    def read_tail(self):
        with self.log.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            stream.seek(max(0, size - 65536))
            return stream.read().decode("utf-8", "replace")

    def stop_process(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)

    def close(self):
        try:
            self.stop_process()
        finally:
            if self.token_file:
                self.token_file.unlink(missing_ok=True)


def take_named_configuration():
    hostname = os.environ.pop("UI_TEST_TUNNEL_HOSTNAME", "")
    token = os.environ.pop("UI_TEST_TUNNEL_TOKEN", "")
    # Cloudflared receives credentials only by file and the app never inherits it.
    if not (hostname or token):
        return {}, 0
    port = int(os.environ.get("UI_TEST_ORIGIN_PORT", "8787"))
    if not 1024 <= port <= 65535 or not HOSTNAME.fullmatch(hostname.lower()) or not token:
        raise ValueError("Configure a named tunnel with a valid hostname, port and secret token.")
    return {"hostname": hostname, "token": token}, port
