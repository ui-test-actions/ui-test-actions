"""Start the runner-owned Cloudflare connector without forwarding its credential."""

import hashlib
import os
import platform
from pathlib import Path
import re
import subprocess
import tarfile
import time
from urllib.request import urlopen


QUICK_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
HOSTNAME = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


CLOUDFLARED_VERSION = "2026.11.1"
CLOUDFLARED_ASSETS = {
    ("Linux", "amd64"): ("linux-amd64", "97bb3b02d23a5980fc9c15a1a270e692da1923f103f920d5b16d4931d5ab55e7"),
    ("Linux", "arm64"): ("linux-arm64", "b155cec3e48e489cfb8e5c602769fb8c771083018d8881d68b4d18a791567c5a"),
    ("Darwin", "amd64"): ("darwin-amd64.tgz", "5e0403b188dfee71fbd9b995e7dc9910d61b661c52371935ab6475d41185632f"),
    ("Darwin", "arm64"): ("darwin-arm64.tgz", "02fe4bcf08f2c09699cff30658228a739a0c47fb75f3653d1b8772a27ade4462"),
    ("Windows", "amd64"): ("windows-amd64.exe", "341deda3db5ec498a0482254d6c38c0b7cf01a30c37bb5dd95d2216d08955e35"),
}
def download_tunnel(work):
    architecture = platform.machine().lower()
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(architecture, architecture)
    suffix, digest = CLOUDFLARED_ASSETS[platform.system(), architecture]
    asset = f"cloudflared-{suffix}"
    url = f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/{asset}"
    download = work / asset
    for attempt in range(3):
        try:
            with urlopen(url, timeout=45) as response, download.open("wb") as destination:
                while chunk := response.read(1024 * 1024):
                    destination.write(chunk)
            break
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    with download.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != digest:
            raise RuntimeError("cloudflared download checksum mismatch")
    binary = work / ("cloudflared.exe" if platform.system() == "Windows" else "cloudflared")
    if suffix.endswith(".tgz"):
        with tarfile.open(download) as archive, binary.open("wb") as destination:
            source = archive.extractfile("cloudflared")
            if source is None:
                raise RuntimeError("cloudflared binary missing from archive")
            destination.write(source.read())
    else:
        download.replace(binary)
    binary.chmod(0o700)
    return binary


class ConnectorUnavailable(RuntimeError):
    """The connector could not establish a working route in its startup budget."""


class ConnectorCancelled(RuntimeError):
    """The job ended while the connector was establishing its route."""


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

    def start(self, deadline, cancelled, probe=None):
        attempt = 0
        reported_routes = 0
        while time.monotonic() < deadline and not cancelled():
            attempt += 1
            try:
                with self.log.open("wb") as output:
                    self.process = subprocess.Popen(self.command, env=self.env, stdout=output, stderr=subprocess.STDOUT)
            except OSError:
                raise ConnectorUnavailable("The Cloudflare connector process could not start.") from None
            attempt_deadline = min(deadline, time.monotonic() + (48 if probe else 37))
            registered = False
            while time.monotonic() < attempt_deadline and not cancelled() and self.process.poll() is None:
                tail = self.read_tail()
                match = QUICK_URL.search(tail)
                if (self.hostname or match) and "Registered tunnel connection" in tail:
                    if not registered:
                        reported_routes += 1
                        registered = True
                    address = "https://" + self.hostname if self.hostname else match.group()
                    if probe is None or probe(address, max(0.1, min(4, attempt_deadline - time.monotonic()))):
                        return address
                time.sleep(0.5)
            self.stop_process()
            if attempt >= 3:
                break
        if cancelled():
            raise ConnectorCancelled("Session startup was cancelled.")
        raise ConnectorUnavailable(
            f"Cloudflare connector did not prove the route after {attempt} attempt(s) "
            f"with {reported_routes} successful edge registration(s). "
            "Check runner egress, route configuration, and Access credentials."
        )

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
