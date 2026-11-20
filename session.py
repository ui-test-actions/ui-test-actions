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

from automation import Automation, error_result
from contract import CommandError
from exchange import Exchange
from tunnel import Tunnel, take_named_configuration


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
    if target == "linux":
        import select
        apt = ("sudo", "apt-get", "-o", "Acquire::Retries=1", "-o", "Acquire::http::Timeout=20",
               "-o", "Acquire::https::Timeout=20")
        packages = ("xvfb", "xauth", "xdotool", "xclip", "openbox", "wmctrl",
                    "python3-pyatspi", "at-spi2-core", "dbus-x11")
        try:
            run(*apt, "install", "-y", "--no-install-recommends", *packages, timeout=100)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            run(*apt, "update", timeout=105)
            run(*apt, "install", "-y", "--no-install-recommends", *packages, timeout=125)
        os.environ.setdefault("QT_LINUX_ACCESSIBILITY_ALWAYS_ON", "1")
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            bus = subprocess.Popen(
                ["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                stdout=subprocess.PIPE, text=True,
            )
            processes.append(bus)
            try:
                if not select.select([bus.stdout], [], [], 5)[0]:
                    raise RuntimeError("The accessibility D-Bus did not start.")
                address = bus.stdout.readline().strip()
                if not address:
                    raise RuntimeError("The accessibility D-Bus reported no address.")
                os.environ["DBUS_SESSION_BUS_ADDRESS"] = address
            finally:
                bus.stdout.close()
    if target == "linux" and not os.environ.get("DISPLAY"):
        read_fd, write_fd = os.pipe()
        try:
            processes.append(subprocess.Popen(
                ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                pass_fds=(write_fd,),
            ))
        finally:
            os.close(write_fd)
        with os.fdopen(read_fd) as pipe:
            if not select.select([pipe], [], [], 8)[0]:
                raise RuntimeError("Xvfb did not report readiness.")
            display = pipe.readline().strip()
        if not display.isdecimal():
            raise RuntimeError("Xvfb did not allocate a display")
        os.environ["DISPLAY"] = f":{display}"
        processes.append(subprocess.Popen(["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        wm_ready = time.monotonic() + 5
        while time.monotonic() < wm_ready:
            if subprocess.run(["wmctrl", "-m"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                break
            time.sleep(0.1)
    deps = ["Pillow==12.2.0"]
    if target in ("windows", "ios"):
        deps.append("PyAutoGUI==0.9.54")
    if target in ("macos", "ios"):
        deps.append("pyobjc-framework-Quartz==12.1")
    if target == "macos":
        deps.append("pyobjc-framework-ApplicationServices==12.1")
    run(sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *deps, timeout=180)
    if target == "windows":
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()


class Desktop:
    def __init__(self, target):
        self.target = target
        if self.target in ("windows", "ios"):
            import pyautogui
            self.gui = pyautogui
            self.gui.FAILSAFE = False
        if self.target in ("macos", "ios"):
            import Quartz
            self.quartz = Quartz

    def capture(self):
        import io
        from PIL import ImageGrab
        image = ImageGrab.grab()
        logical_size = image.size
        if self.target in ("macos", "ios"):
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
        if self.target in ("windows", "ios"):
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
    def __init__(self, digest, backend, target, driver=None, port=0, exchange=None):
        super().__init__(("127.0.0.1", port), Handler)
        self.digest = digest
        self.backend = backend
        self.target = target
        self.lock = threading.Lock()
        self.id = os.urandom(12).hex()
        self.deadline = 0
        self.size = (0, 0)
        self.automation = Automation(self, driver, exchange)
        self.workers = threading.BoundedSemaphore(24)

    def process_request(self, request, address):
        if not self.workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.workers.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.workers.release()

    def handle_error(self, request, address):
        # Request bodies, authorization headers and platform arguments are never logged here.
        print("An HTTP request ended unexpectedly", flush=True)

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
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
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
            if self.path == "/v2/capabilities":
                self.reply(200, {
                    "api_version": 2, "id": self.server.id, "target": self.server.target,
                    "screen": {"width": self.server.size[0], "height": self.server.size[1]},
                    "commands": self.server.automation.capabilities(),
                    "limits": {"max_batch_steps": 12, "replay_window": 64, "max_request_bytes": 65536},
                })
            elif self.path == "/v2/recording":
                data = self.server.automation.recording.latest
                if data:
                    self.reply(200, data, "image/gif")
                else:
                    self.reply(404, {"ok": False, "error": {
                        "code": "recording_missing", "message": "Stop a recording before downloading it.",
                    }})
            elif self.path == "/v1/session":
                self.reply(200, {
                    "id": self.server.id,
                    "target": self.server.target,
                    "seconds_remaining": max(0, round(self.server.deadline - time.monotonic())),
                })
            elif self.path == "/v1/screenshot":
                if not self.server.lock.acquire(blocking=False):
                    self.reply(429, {"error": "The session is busy"})
                    return
                try:
                    if time.monotonic() >= self.server.deadline:
                        self.reply(410, {"error": "Session ended"})
                        return
                    try:
                        screenshot = self.server.capture()
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                        print(f"Screenshot backend error: {type(error).__name__}", flush=True)
                        self.reply(502, {"error": "Screenshot failed"})
                        return
                finally:
                    self.server.lock.release()
                self.reply(200, screenshot, "image/png")
            else:
                self.reply(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path in ("/v2/action", "/v2/batch"):
            self.execute_v2()
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
                self.server.automation.snapshot = None
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

    def execute_v2(self):
        try:
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                raise CommandError("invalid_request", "Provide a single Content-Length header.")
            if self.headers.get_content_type() != "application/json":
                raise CommandError("invalid_media_type", "Expected application/json.", 415)
            try:
                size = int(self.headers["Content-Length"])
            except ValueError:
                raise CommandError("invalid_request", "Invalid Content-Length.") from None
            if not 1 <= size <= 65536:
                raise CommandError("request_too_large", "The request must contain 1–65536 bytes.", 413)
            try:
                request = json.loads(self.rfile.read(size).decode("utf-8"))
            except (ValueError, RecursionError):
                raise CommandError("invalid_json", "Provide well-formed UTF-8 JSON.") from None
            if not self.server.lock.acquire(blocking=False):
                raise CommandError("session_busy", "Another command is running. Retry the same request ID.", 429)
            try:
                self.server.automation.check_live()
                status, payload = self.server.automation.execute(request, batch=self.path == "/v2/batch")
            finally:
                self.server.lock.release()
        except CommandError as error:
            status, payload = error.status, {"ok": False, "error": error_result(error)}
        self.reply(status, payload)

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


class SimulatorDriver:
    def __init__(self, mobile, window):
        self.mobile = mobile
        self.window = window

    def capabilities(self):
        return set(self.mobile.capabilities()) | set(self.window.capabilities())

    def execute(self, command, params):
        driver = self.mobile if command in self.mobile.capabilities() else self.window
        return driver.execute(command, params)

    def close(self):
        self.mobile.close()


def load_driver(backend, target):
    if target in ("android", "ios"):
        from desktop_driver import DesktopDriver
        from mobile_driver import MobileDriver
        mobile = MobileDriver(backend, target)
        return SimulatorDriver(mobile, DesktopDriver(backend, target)) if target == "ios" else mobile
    from desktop_driver import DesktopDriver
    return DesktopDriver(backend, target)


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
    named, port = take_named_configuration()
    processes = []
    driver = tunnel = None
    with tempfile.TemporaryDirectory(prefix="live-ui-") as directory:
        work = Path(directory)
        try:
            binary = download_tunnel(work)
            device = os.environ.get("UI_TEST_DEVICE", "")
            webdriver_url = os.environ.get("UI_TEST_WEBDRIVER_URL")
            native_ios = target == "ios" and bool(webdriver_url)
            if target != "android" and not native_ios:
                setup_desktop(target, processes)
            if target == "ios" and not native_ios:
                from mobile import open_simulator
                open_simulator(device)
            exchange = None
            if target in ("linux", "windows", "macos") and os.environ.get("UI_TEST_FILE_EXCHANGE") == "1":
                exchange = Exchange(work / "files")
                os.environ["UI_TEST_EXCHANGE_DIR"] = str(exchange.directory)
            launch_app(startup)
            if target == "android" or native_ios:
                run(sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "Pillow==12.2.0", timeout=180)
            if target == "android":
                from mobile import Android
                backend = Android(device)
            else:
                backend = None if native_ios else Desktop(target)
            if native_ios:
                from mobile_driver import MobileDriver
                driver = MobileDriver(None, target)
            else:
                driver = load_driver(backend, target)
            if webdriver_url:
                if target not in ("android", "ios"):
                    raise ValueError("The loopback Appium adapter requires an Android or iOS target.")
                from webdriver_driver import WebDriverMobile
                driver = WebDriverMobile(
                    webdriver_url, json.loads(os.environ["UI_TEST_WEBDRIVER_CAPS"]), driver, target,
                )
                backend = driver
            with Session(digest, backend, target, driver, port, exchange) as session:
                session.capture()
                serving = threading.Thread(target=session.serve_forever, daemon=True)
                serving.start()
                try:
                    tunnel = Tunnel(binary, session.server_port, work, **named)
                    cancelled = (control / "stop").exists
                    address = tunnel.start(time.monotonic() + 110, cancelled)
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
                        if tunnel.process.poll() is not None:
                            if not tunnel.hostname:
                                raise RuntimeError("The Quick Tunnel process exited. Start a fresh session.")
                            print("Restarting the named Cloudflare connector", flush=True)
                            tunnel.start(min(time.monotonic() + 55, session.deadline), cancelled)
                        time.sleep(min(remaining, 0.25))
                finally:
                    session.deadline = 0
                    session.automation.recording.stop.set()
                    session.shutdown()
        finally:
            if tunnel:
                try:
                    tunnel.close()
                except (RuntimeError, OSError, subprocess.SubprocessError):
                    print("The Cloudflare connector could not complete cleanup", flush=True)
            if hasattr(driver, "close"):
                try:
                    driver.close()
                except (RuntimeError, OSError, subprocess.SubprocessError):
                    print("The platform driver could not complete cleanup", flush=True)
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
