"""UI input and framebuffer capture on local mobile simulators."""

import hashlib
import json
import platform
from shlex import quote
from struct import unpack
import subprocess
import sys
import tarfile
import time
from urllib.request import urlopen


IDB_RELEASE = "https://github.com/meta/idb/releases/download/v1.7.8/"
IDB_ARCHIVE = "idb-companion.macos-arm64.tar.gz"
IDB_WHEEL = "fb_idb-1.7.8-py3-none-any.whl"
IDB_DIGESTS = {
    IDB_ARCHIVE: "44369a2df0b62e3a1764de61bd09280999c7e9b27ea8f20bff1ea3a9db0302a2",
    IDB_WHEEL: "ed8557a4c54ffee53006c1fe63f070cda567949312ab24be56faf987c5a3d04b",
}


def output(*args, timeout=20):
    return subprocess.check_output(args, timeout=timeout)


def select_device(requested, available, kind):
    if requested:
        if requested not in available:
            raise RuntimeError(f"Requested {kind} is unavailable")
        return requested
    if len(available) != 1:
        raise RuntimeError(f"Expected one {kind}, or set the device input")
    return available[0]


class Android:
    def __init__(self, device):
        listing = output("adb", "devices").decode().splitlines()[1:]
        online = [line.split()[0] for line in listing if line.split()[1:] == ["device"]]
        self.adb = ("adb", "-s", select_device(device, online, "online ADB device"))

    def capture(self):
        return output(*self.adb, "exec-out", "screencap", "-p")

    def pointer(self, kind, points, duration):
        coords = " ".join(str(value) for point in points for value in point)
        command = f"tap {coords}" if kind == "click" else f"swipe {coords} {round(duration * 1000)}"
        output(*self.adb, "shell", f"input {command}")

    def type_text(self, text):
        # Android input interprets %s as a space. Send literal percent signs separately.
        escaped = quote(text.replace(" ", "%s"))
        if "%s" not in text:
            output(*self.adb, "shell", f"input text {escaped}")
            return
        parts = text.split("%s")
        commands = []
        for index, part in enumerate(parts):
            if index:
                commands.extend(("input text '%'", "input text 's'"))
            if part:
                commands.append("input text " + quote(part.replace(" ", "%s")))
        output(*self.adb, "shell", " && ".join(commands))


class IOS:
    def __init__(self, device, work, processes):
        if platform.machine() != "arm64":
            raise RuntimeError("The iOS backend requires an Apple Silicon runner")
        booted = json.loads(output("xcrun", "simctl", "list", "devices", "booted", "-j"))
        devices = [
            item["udid"] for runtime, items in booted["devices"].items()
            if ".iOS-" in runtime for item in items if item["state"] == "Booted"
        ]
        self.udid = select_device(device, devices, "booted iOS simulator")
        self.work = work
        self.screen = (0, 0)
        for name, digest in IDB_DIGESTS.items():
            with urlopen(IDB_RELEASE + name, timeout=45) as source, (work / name).open("wb") as dest:
                while chunk := source.read(1024 * 1024):
                    dest.write(chunk)
            with (work / name).open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != digest:
                    raise RuntimeError(f"IDB checksum mismatch for {name}")
        with tarfile.open(work / IDB_ARCHIVE) as archive:
            archive.extractall(work / "idb", filter="data")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", str(work / IDB_WHEEL)],
            check=True, timeout=180,
        )
        socket = work / "idb.sock"
        self.idb = ("idb", "--companion", str(socket))
        log = work / "idb.log"
        with log.open("wb") as stream:
            companion = subprocess.Popen(
                [str(work / "idb" / "idb_companion"), "--udid", self.udid, "--grpc-domain-sock", str(socket)],
                stdout=stream, stderr=subprocess.STDOUT,
            )
        processes.append(companion)
        deadline = time.monotonic() + 45
        while not socket.exists() and companion.poll() is None and time.monotonic() < deadline:
            time.sleep(0.25)
        if not socket.exists():
            print(log.read_text(encoding="utf-8", errors="replace"))
            raise RuntimeError("IDB companion did not start")
        dims = json.loads(output(*self.idb, "describe", "--json"))["screen_dimensions"]
        self.points = (dims["width_points"], dims["height_points"])
        if not all(self.points):
            raise RuntimeError("Simulator did not report logical screen dimensions")

    def capture(self):
        path = self.work / "screen.png"
        output("xcrun", "simctl", "io", self.udid, "screenshot", "--type=png", str(path))
        png = path.read_bytes()
        self.screen = unpack(">II", png[16:24])
        return png

    def pointer(self, kind, points, duration):
        width, height = self.points
        image_width, image_height = self.screen
        if (width > height) != (image_width > image_height):
            width, height = height, width
        coordinates = [
            str(value)
            for x, y in points
            for value in (x * width // image_width, y * height // image_height)
        ]
        if kind == "click":
            output(*self.idb, "ui", "tap", *coordinates)
        else:
            output(*self.idb, "ui", "swipe", *coordinates, "--duration", str(duration))

    def type_text(self, text):
        output(*self.idb, "ui", "text", "--", text)
