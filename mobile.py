"""UI input and framebuffer capture on local mobile simulators."""

import json
from shlex import quote
import subprocess


def output(*args, timeout=20, stderr=None):
    return subprocess.check_output(args, timeout=timeout, stderr=stderr)


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
            output(*self.adb, "shell", f"input text {escaped}", stderr=subprocess.DEVNULL)
            return
        parts = text.split("%s")
        commands = []
        for index, part in enumerate(parts):
            if index:
                commands.extend(("input text '%'", "input text 's'"))
            if part:
                commands.append("input text " + quote(part.replace(" ", "%s")))
        output(*self.adb, "shell", " && ".join(commands), stderr=subprocess.DEVNULL)


def open_simulator(device):
    for timeout in (20, 40):
        try:
            booted = json.loads(output("xcrun", "simctl", "list", "devices", "booted", "-j", timeout=timeout))
            break
        except subprocess.TimeoutExpired:
            if timeout == 40:
                raise
    devices = [
        item["udid"] for runtime, items in booted["devices"].items()
        if ".iOS-" in runtime for item in items if item["state"] == "Booted"
    ]
    udid = select_device(device, devices, "booted iOS simulator")
    output("open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", udid)
    return udid
