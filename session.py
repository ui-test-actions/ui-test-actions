"""Start a UI session and publish its temporary HTTPS address."""

import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from urllib.request import urlopen


CLOUDFLARED_VERSION = "2026.11.1"
CLOUDFLARED_ASSETS = {
    ("Linux", "amd64"): ("linux-amd64", "97bb3b02d23a5980fc9c15a1a270e692da1923f103f920d5b16d4931d5ab55e7"),
    ("Linux", "arm64"): ("linux-arm64", "b155cec3e48e489cfb8e5c602769fb8c771083018d8881d68b4d18a791567c5a"),
    ("Darwin", "amd64"): ("darwin-amd64.tgz", "5e0403b188dfee71fbd9b995e7dc9910d61b661c52371935ab6475d41185632f"),
    ("Darwin", "arm64"): ("darwin-arm64.tgz", "02fe4bcf08f2c09699cff30658228a739a0c47fb75f3653d1b8772a27ade4462"),
    ("Windows", "amd64"): ("windows-amd64.exe", "341deda3db5ec498a0482254d6c38c0b7cf01a30c37bb5dd95d2216d08955e35"),
}
TARGET_OS = {"linux": "Linux", "windows": "Windows", "macos": "Darwin", "android": "Linux", "ios": "Darwin"}
ROOT = Path(__file__).resolve().parent


def run(*args, timeout=20, **kwargs):
    return subprocess.run(args, check=True, timeout=timeout, **kwargs)


def duration_setting(name, low, high):
    value = int(os.environ[name])
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def setup_desktop(target, processes):
    if target == "linux" and not os.environ.get("DISPLAY"):
        run("sudo", "apt-get", "update", timeout=120)
        run("sudo", "apt-get", "install", "-y", "xvfb", "xauth", "xdotool", timeout=120)
        read_fd, write_fd = os.pipe()
        try:
            processes.append(subprocess.Popen(
                ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                pass_fds=(write_fd,),
            ))
        finally:
            os.close(write_fd)
        with os.fdopen(read_fd) as pipe:
            display = pipe.readline().strip()
        if not display.isdecimal():
            raise RuntimeError("Xvfb did not allocate a display")
        os.environ["DISPLAY"] = f":{display}"
    deps = ["Pillow==12.2.0"]
    if target == "windows":
        deps.append("PyAutoGUI==0.9.54")
    if target == "macos":
        deps.append("pyobjc-framework-Quartz==12.1")
    run(sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *deps, timeout=180)
    if target == "windows":
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()


class Desktop:
    def __init__(self, target):
        self.target = target
        if self.target == "windows":
            import pyautogui
            self.gui = pyautogui
            self.gui.FAILSAFE = False
        if self.target == "macos":
            import Quartz
            self.quartz = Quartz

    def capture(self):
        import io
        from PIL import ImageGrab
        image = ImageGrab.grab()
        logical_size = image.size
        if self.target == "macos":
            q = self.quartz
            bounds = q.CGDisplayBounds(q.CGMainDisplayID())
            logical_size = (int(bounds.size.width), int(bounds.size.height))
            if image.size != logical_size:
                image = image.resize(logical_size)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()

    def pointer(self, kind, points, duration):
        x, y = points[0]
        if self.target == "windows":
            self.gui.moveTo(x, y)
            if kind == "click":
                self.gui.click()
            else:
                self.gui.dragTo(*points[1], duration=duration, button="left")
        elif self.target == "linux":
            run("xdotool", "mousemove", str(x), str(y))
            if kind == "click":
                run("xdotool", "click", "1")
            else:
                run("xdotool", "mousedown", "1")
                try:
                    self.interpolate(points, duration, lambda x, y: run("xdotool", "mousemove", str(x), str(y)))
                finally:
                    run("xdotool", "mouseup", "1")
        else:
            q = self.quartz

            def post(event, x, y):
                q.CGEventPost(q.kCGHIDEventTap, q.CGEventCreateMouseEvent(None, event, (x, y), q.kCGMouseButtonLeft))

            post(q.kCGEventMouseMoved, x, y)
            post(q.kCGEventLeftMouseDown, x, y)
            if kind == "swipe":
                self.interpolate(points, duration, lambda x, y: post(q.kCGEventLeftMouseDragged, x, y))
            post(q.kCGEventLeftMouseUp, *points[-1])

    @staticmethod
    def interpolate(points, duration, move):
        (x1, y1), (x2, y2) = points
        for step in range(1, 13):
            time.sleep(duration / 12)
            move(round(x1 + (x2 - x1) * step / 12), round(y1 + (y2 - y1) * step / 12))

    def type_text(self, text):
        if self.target == "windows":
            self.gui.write(text, interval=0.025)
        elif self.target == "linux":
            run("xdotool", "type", "--clearmodifiers", "--", text)
        else:
            q = self.quartz
            for character in text:
                for down in (True, False):
                    event = q.CGEventCreateKeyboardEvent(None, 0, down)
                    length = len(character.encode("utf-16-le")) // 2
                    q.CGEventKeyboardSetUnicodeString(event, length, character)
                    q.CGEventPost(q.kCGHIDEventTap, event)


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


class Session(ThreadingHTTPServer):
    def __init__(self, digest, backend, target):
        super().__init__(("127.0.0.1", 0), Handler)
        self.digest = digest
        self.backend = backend
        self.target = target
        self.lock = threading.Lock()
        self.id = os.urandom(12).hex()
        self.deadline = 0
        self.size = (0, 0)

    def capture(self):
        from struct import unpack
        png = self.backend.capture()
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Backend returned an invalid PNG")
        self.size = unpack(">II", png[16:24])
        return png


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(10)
        super().setup()

    def log_message(self, *_args):
        pass

    def reply(self, code, payload, content_type="application/json"):
        if isinstance(payload, dict):
            payload = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(payload)

    def authorized(self):
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not re.fullmatch(r"[0-9a-f]{64}", token):
            self.reply(401, {"error": "Bearer token required"})
            return False
        if not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), self.server.digest):
            self.reply(401, {"error": "Invalid session token"})
            return False
        if time.monotonic() >= self.server.deadline:
            self.reply(410, {"error": "Session ended"})
            return False
        return True

    def do_GET(self):
        if self.path == "/":
            self.reply(200, (ROOT / "client.html").read_bytes(), "text/html; charset=utf-8")
        elif self.authorized():
            if self.path == "/v1/session":
                self.reply(200, {
                    "id": self.server.id,
                    "target": self.server.target,
                    "seconds_remaining": max(0, round(self.server.deadline - time.monotonic())),
                })
            elif self.path == "/v1/screenshot":
                with self.server.lock:
                    try:
                        screenshot = self.server.capture()
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                        print(f"Screenshot backend error: {type(error).__name__}", flush=True)
                        self.reply(502, {"error": "Screenshot failed"})
                        return
                self.reply(200, screenshot, "image/png")
            else:
                self.reply(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/v1/input":
            self.reply(404, {"error": "Unknown endpoint"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 4096:
                raise ValueError("Expected a JSON request of 1–4096 bytes")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            with self.server.lock:
                if time.monotonic() >= self.server.deadline:
                    self.reply(410, {"error": "Session ended"})
                    return
                self.apply_input(data)
        except (ValueError, KeyError, TypeError) as error:
            message = str(error) if type(error) is ValueError else "Malformed input"
            self.reply(400, {"error": message})
            return
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            print(f"Input backend error: {type(error).__name__}", flush=True)
            self.reply(502, {"error": "Input failed"})
            return
        self.reply(200, {"ok": True})

    def apply_input(self, data):
        kind = data.get("action")
        if kind == "type":
            entry = data.get("text")
            if not isinstance(entry, str) or not re.fullmatch(r"[ -~]{1,256}", entry):
                raise ValueError("Text must be 1–256 printable ASCII characters")
            self.server.backend.type_text(entry)
            return
        if kind not in ("click", "swipe"):
            raise ValueError("Expected click, swipe, or type")
        coordinates = [("x", "y")] if kind == "click" else [("x", "y"), ("end_x", "end_y")]
        width, height = self.server.size
        points = []
        for x_key, y_key in coordinates:
            x, y = data.get(x_key), data.get(y_key)
            if type(x) is not int or type(y) is not int or not (0 <= x < width and 0 <= y < height):
                raise ValueError("Use integer coordinates within the latest screenshot")
            points.append((x, y))
        milliseconds = data.get("duration_ms", 400)
        if type(milliseconds) is not int or not 100 <= milliseconds <= 3000:
            raise ValueError("duration_ms must be between 100 and 3000")
        self.server.backend.pointer(kind, points, milliseconds / 1000)


def start_tunnel(binary, port, log, processes):
    config = log.with_suffix(".yml")
    config.write_text("{}\n", encoding="utf-8")
    with log.open("wb") as output:
        tunnel = subprocess.Popen([
            str(binary), "--config", str(config), "tunnel", "--no-autoupdate",
            "--protocol", "http2", "--url", f"http://127.0.0.1:{port}",
        ], stdout=output, stderr=subprocess.STDOUT)
    processes.append(tunnel)
    deadline = time.monotonic() + 85
    while time.monotonic() < deadline and tunnel.poll() is None:
        diagnostics = log.read_text(encoding="utf-8", errors="replace")
        address = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", diagnostics)
        if address and "Registered tunnel connection" in diagnostics:
            return address.group()
        time.sleep(1)
    print(log.read_text(encoding="utf-8", errors="replace"))
    raise RuntimeError("Cloudflare tunnel did not connect")


def launch_app(timeout):
    deadline = time.monotonic() + timeout
    bash = os.environ.get("UI_TEST_BASH", "bash")
    launch = os.environ.get("UI_TEST_LAUNCH")
    if launch:
        print("Starting the application")
        run(bash, "-e", "-c", launch, timeout=timeout)
    ready = os.environ.get("UI_TEST_READY")
    if ready:
        print("Waiting for the application readiness check")
        while (remaining := deadline - time.monotonic()) > 0:
            result = subprocess.run(
                [bash, "-c", ready], timeout=remaining, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                return
            time.sleep(1)
        raise RuntimeError("Application readiness check timed out")


def stop(*_args):
    raise KeyboardInterrupt


def main(control):
    signal.signal(signal.SIGTERM, stop)
    target = os.environ["UI_TEST_TARGET"]
    if TARGET_OS.get(target) != platform.system():
        raise ValueError("Target must match the operating system of the runner")
    digest = os.environ["UI_TEST_TOKEN_SHA256"]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("token-sha256 must be a 64-character lowercase SHA-256 hex digest")
    duration = duration_setting("UI_TEST_DURATION", 1, 180)
    startup = duration_setting("UI_TEST_STARTUP_TIMEOUT", 1, 1800)
    processes = []
    with tempfile.TemporaryDirectory(prefix="live-ui-") as directory:
        work = Path(directory)
        try:
            binary = download_tunnel(work)
            setup_desktop(target, processes)
            launch_app(startup)
            with Session(digest, Desktop(target), target) as session:
                session.capture()
                serving = threading.Thread(target=session.serve_forever, daemon=True)
                serving.start()
                try:
                    address = start_tunnel(binary, session.server_port, work / "tunnel.log", processes)
                    session.deadline = time.monotonic() + duration * 60
                    print(f"UI_SESSION_URL={address}")
                    print(f"{target} session ready for {duration} minute(s)")
                    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                        summary.write(f"### Live UI session\n\n[{target}]({address}) · {duration} minute(s)\n")
                    data = {
                        "url": address,
                        "target": target,
                        "session_id": session.id,
                        "expires_unix": int(time.time() + duration * 60),
                    }
                    unpublished = control / "connection.tmp"
                    unpublished.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                    unpublished.replace(control / "connection.json")
                    while (remaining := session.deadline - time.monotonic()) > 0 and not (control / "stop").exists():
                        if processes[-1].poll() is not None:
                            raise RuntimeError("Cloudflare process exited during the session")
                        time.sleep(min(remaining, 0.25))
                finally:
                    session.deadline = 0
                    session.shutdown()
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    control = Path(sys.argv[1])
    outcome = "failure"
    try:
        main(control)
        outcome = "success"
    finally:
        temporary = control / "outcome.tmp"
        temporary.write_text(outcome, encoding="utf-8")
        temporary.replace(control / "outcome")
