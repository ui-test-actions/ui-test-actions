"""UI input and framebuffer capture on local mobile simulators."""

import json
from shlex import quote
import subprocess
from uuid import UUID


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


def simulator_startup_output(*args):
    for timeout in (20, 40):
        try:
            return output(*args, timeout=timeout)
        except subprocess.TimeoutExpired:
            if timeout == 40:
                raise


def open_simulator(device):
    udid = selected_simulator(device)
    simulator_startup_output("open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", udid)
    return udid


def selected_simulator(requested):
    if requested:
        try:
            udid = str(UUID(requested)).upper()
            processes = output("xcrun", "simctl", "spawn", udid, "launchctl", "list",
                               timeout=18, stderr=subprocess.DEVNULL)
        except (ValueError, OSError, subprocess.SubprocessError):
            pass
        else:
            for line in processes.splitlines():
                fields = line.split()
                if len(fields) == 3 and fields[0].isdigit() and fields[2] == b"com.apple.SpringBoard":
                    return udid
    booted = json.loads(simulator_startup_output("xcrun", "simctl", "list", "devices", "booted", "-j"))
    devices = [
        item["udid"] for runtime, items in booted["devices"].items()
        if ".iOS-" in runtime for item in items if item["state"] == "Booted"
    ]
    return select_device(requested, devices, "booted iOS simulator")
