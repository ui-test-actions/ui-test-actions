"""Allowlisted automation commands for Android emulators and iOS simulators."""

import base64
import json
import os
from pathlib import Path
import plistlib
import re
from shlex import quote
import struct
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
import uuid
from xml.etree import ElementTree

from contract import CommandError
from mobile import select_device


_PACKAGE_ID = re.compile(r"[A-Za-z][A-Za-z_0-9]*(?:\.[A-Za-z_0-9][A-Za-z_0-9-]*)+")
_IME_ID = "dev.uitest.sessionime/.SessionIme"
_IME_PACKAGE = "dev.uitest.sessionime"
_IME_ACTION = "dev.uitest.sessionime.OPERATION"
_MAX_TEXT_BYTES = 16384
_MAX_HIERARCHY_BYTES = 2 << 20
_ANDROID_KEYS = {
    "alt": "ALT_LEFT", "back": "BACK", "backspace": "DEL", "ctrl": "CTRL_LEFT",
    "delete": "FORWARD_DEL", "end": "MOVE_END", "enter": "ENTER", "esc": "ESCAPE",
    "home": "MOVE_HOME", "left": "DPAD_LEFT", "meta": "META_LEFT", "pagedown": "PAGE_DOWN",
    "pageup": "PAGE_UP", "right": "DPAD_RIGHT", "shift": "SHIFT_LEFT", "space": "SPACE",
    "tab": "TAB", "up": "DPAD_UP", "down": "DPAD_DOWN", "devicehome": "HOME",
    "volumeup": "VOLUME_UP", "volumedown": "VOLUME_DOWN", "appswitch": "APP_SWITCH",
    "menu": "MENU", "pause": "BREAK", "insert": "INSERT", "capslock": "CAPS_LOCK",
    "printscreen": "SYSRQ", "numlock": "NUM_LOCK", "scrolllock": "SCROLL_LOCK",
    "-": "MINUS", "+": "PLUS",
}
_ANDROID_KEYS.update({"arrow" + key: _ANDROID_KEYS[key] for key in ("up", "down", "left", "right")})
_ANDROID_KEYS.update({f"f{number}": f"F{number}" for number in range(1, 13)})
_ANDROID_KEYS.update({key: key.upper() for key in "abcdefghijklmnopqrstuvwxyz0123456789"})
_KEY_ALIASES = {
    "control": "ctrl", "command": "meta", "cmd": "meta", "win": "meta", "super": "meta",
    "option": "alt", "escape": "esc", "return": "enter", "page-up": "pageup",
    "page-down": "pagedown", "del": "delete", "spacebar": "space",
}
_ANDROID_ROTATIONS = {
    "portrait": "0", "landscape": "1", "reverse_portrait": "2", "reverse_landscape": "3",
}
_ANDROID_ROLES = {
    "Button": "button", "CheckBox": "checkbox", "EditText": "textbox", "ImageButton": "button",
    "ImageView": "image", "RadioButton": "radio", "SeekBar": "slider", "Spinner": "combobox",
    "Switch": "switch", "TextView": "text", "ToggleButton": "button", "ScrollView": "scrollarea",
    "ListView": "list", "RecyclerView": "list",
}


def _run(*args, stdin=None, timeout=20):
    try:
        return subprocess.run(
            args, input=stdin, check=True, capture_output=True, timeout=timeout,
        ).stdout
    except subprocess.TimeoutExpired as error:
        raise subprocess.TimeoutExpired(Path(args[0]).name, error.timeout) from None
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"{Path(args[0]).name} returned exit code {error.returncode}") from None


def _utf8(text):
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    encoded = text.encode("utf-8")
    if b"\0" in encoded or len(encoded) > _MAX_TEXT_BYTES:
        raise ValueError("text cannot contain NUL or exceed 16 KiB as UTF-8")
    return encoded


def _key(key):
    name = _KEY_ALIASES.get(key.lower(), key.lower())
    if name.startswith("key") and len(name) == 4:
        name = name[3:]
    if name.startswith("digit") and len(name) == 6:
        name = name[5:]
    if name not in _ANDROID_KEYS:
        raise ValueError("Android keyboard key is unsupported")
    return "KEYCODE_" + _ANDROID_KEYS[name]


def parse_android_tree(data):
    if len(data) > _MAX_HIERARCHY_BYTES or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise RuntimeError("Android UI hierarchy exceeds its safe document limits")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        raise RuntimeError("Android UI hierarchy is unavailable or invalid") from None
    result = []
    stack = [(child, None) for child in reversed(list(root))]
    while stack:
        node, parent = stack.pop()
        if node.tag != "node":
            continue
        if len(result) == 4000:
            raise RuntimeError("Android UI hierarchy exceeds 4000 nodes")
        attrs = node.attrib
        kind = attrs.get("class", "").rsplit(".", 1)[-1]
        secret = attrs.get("password") == "true"
        geometry = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", attrs.get("bounds", ""))
        bounds = None
        if geometry:
            x, y, right, bottom = map(int, geometry.groups())
            bounds = {"x": x, "y": y, "width": max(0, right - x), "height": max(0, bottom - y)}
        identifier = str(len(result) + 1)
        result.append({
            "id": identifier,
            "parent_id": parent,
            "name": "" if secret else attrs.get("content-desc", "")[:1024],
            "text": "" if secret else attrs.get("text", "")[:4096],
            "role": _ANDROID_ROLES.get(kind, kind or "view"),
            "visible": bool(bounds and bounds["width"] and bounds["height"])
                       and attrs.get("visible-to-user") != "false",
            "bounds": bounds,
            "enabled": attrs.get("enabled") != "false",
            "resource_id": attrs.get("resource-id", "")[:512],
            "properties": {
                "resource_id": attrs.get("resource-id", "")[:512],
                "class": attrs.get("class", "")[:256],
                "package": attrs.get("package", "")[:256],
                **{flag: attrs.get(flag) == "true" for flag in (
                    "clickable", "long-clickable", "scrollable", "enabled", "focusable",
                    "focused", "checkable", "checked", "selected", "password",
                )},
            },
        })
        stack.extend((child, identifier) for child in reversed(list(node)))
    return {"nodes": result}


class AndroidIme:
    def __init__(self, driver):
        self.driver = driver
        self.installed = False
        self.previous = None
        self.active = False

    def install(self):
        home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        if not home:
            raise RuntimeError("ANDROID_HOME must point to the SDK to build the test input method")
        sdk = Path(home)
        tools = sdk / "build-tools" / "35.0.0"
        jar = sdk / "platforms" / "android-35" / "android.jar"
        source = Path(__file__).resolve().parent / "mobile_ime"
        if self.driver.shell("pm", "list", "packages", _IME_PACKAGE).splitlines().count(
            f"package:{_IME_PACKAGE}".encode()
        ):
            raise RuntimeError("A test IME with the reserved package ID is already installed")
        with tempfile.TemporaryDirectory(prefix="uitest-ime-") as directory:
            build = Path(directory)
            classes = build / "classes"
            dex = build / "dex"
            classes.mkdir()
            dex.mkdir()
            apk = build / "ime.apk"
            key = build / "ime.jks"
            _run("javac", "--release", "8", "-encoding", "UTF-8", "-classpath", str(jar),
                 "-d", str(classes), str(source / "SessionIme.java"), timeout=40)
            bytecode = sorted(str(file) for file in classes.rglob("*.class"))
            _run(str(tools / "d8"), "--lib", str(jar), "--min-api", "26",
                 "--output", str(dex), *bytecode, timeout=40)
            _run(str(tools / "aapt"), "package", "-f", "-M", str(source / "AndroidManifest.xml"),
                 "-I", str(jar), "-S", str(source / "res"), "-F", str(apk))
            # APK entries need to preserve only the classes.dex name.
            result = subprocess.run(
                [str(tools / "aapt"), "add", str(apk), "classes.dex"], cwd=dex,
                capture_output=True, timeout=20, check=False,
            )
            if result.returncode:
                raise RuntimeError("Android build tools could not add the IME bytecode")
            _run("keytool", "-genkeypair", "-noprompt", "-keystore", str(key), "-storepass", "android",
                 "-keypass", "android", "-alias", "uitest", "-keyalg", "RSA", "-keysize", "2048",
                 "-validity", "2", "-dname", "CN=Temporary UI Test Session Input", timeout=40)
            _run(str(tools / "apksigner"), "sign", "--ks", str(key), "--ks-pass", "pass:android", str(apk))
            self.driver.adb("install", str(apk), timeout=60)
            self.installed = True

    def _broadcast(self, operation, text=None, *, activate=True):
        if activate:
            self.activate()
        args = ["am", "broadcast", "--receiver-foreground", "-a", _IME_ACTION,
                "-p", _IME_PACKAGE, "--es", "operation", operation]
        if text is not None:
            args.extend(("--es", "payload", base64.b64encode(_utf8(text)).decode("ascii")))
        response = self.driver.shell(*args, timeout=5).decode("utf-8", errors="replace")
        match = re.search(r'result=(\d+)(?:, data="([A-Za-z0-9+/=]*)")?', response)
        return (int(match[1]), match[2]) if match else (0, None)

    def activate(self):
        if self.active:
            return
        if self.previous is None:
            self.previous = self.driver.shell("settings", "get", "secure", "default_input_method").decode().strip()
        self.driver.shell("ime", "enable", _IME_ID)
        self.driver.shell("ime", "set", _IME_ID)
        for _ in range(8):
            if self._broadcast("ping", activate=False)[0] == 42:
                self.active = True
                return
            time.sleep(0.125)
        raise RuntimeError("Android test input method did not register with the emulator")

    def execute(self, operation, text=None):
        for _ in range(4):
            code, data = self._broadcast(operation, text)
            if code == 42:
                return base64.b64decode(data or "", validate=True).decode("utf-8")
            if code != 43:
                break
            time.sleep(0.125)
        if code == 43:
            raise ValueError("Focus an editable Android field before inserting text")
        raise RuntimeError("Android input method or focused application rejected the requested operation")

    def close(self):
        try:
            if self.previous and self.previous not in ("null", _IME_ID):
                self.driver.shell("ime", "set", self.previous, timeout=3)
        finally:
            if self.installed:
                try:
                    if self.previous is not None:
                        self.driver.shell("ime", "disable", _IME_ID, timeout=3)
                finally:
                    self.driver.adb("uninstall", _IME_PACKAGE, timeout=5)


class MobileDriver:
    def __init__(self, legacy, target):
        if target not in {"android", "ios"}:
            raise ValueError("Mobile driver requires Android or iOS")
        self.legacy = legacy
        self.target = target
        self.app_ids = frozenset(
            item.strip() for item in os.environ.get("UI_TEST_APP_IDS", "").split(",") if item.strip()
        )
        if not all(_PACKAGE_ID.fullmatch(item) and item != _IME_PACKAGE for item in self.app_ids):
            raise ValueError("Configured mobile app IDs must be package or bundle IDs")
        self.install_paths = json.loads(os.environ.get("UI_TEST_APP_INSTALLS") or "{}")
        if not isinstance(self.install_paths, dict) or any(
            key not in self.app_ids or not isinstance(path, str) or not path
            for key, path in self.install_paths.items()
        ):
            raise ValueError("Configure app install paths as an object keyed by allowlisted app ID")
        self.url_schemes = frozenset(
            item.strip().lower()
            for item in os.environ.get("UI_TEST_DEEPLINK_SCHEMES", "").split(",")
            if item.strip()
        )
        if not all(re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme) for scheme in self.url_schemes):
            raise ValueError("Configure a comma-separated list of URL schemes")
        if self.url_schemes & {"file", "javascript", "data", "intent"}:
            raise ValueError("Local file, executable and Android intent URL schemes are unsupported")
        self.ime = None
        self.previous_rotation = None
        if target == "android":
            if os.environ.get("UI_TEST_ANDROID_IME", "1") != "0":
                ime = AndroidIme(self)
                try:
                    if not legacy.adb[-1].startswith("emulator-"):
                        raise RuntimeError("The temporary test input method requires an Android emulator")
                    ime.install()
                except subprocess.TimeoutExpired:
                    print("Android Unicode and clipboard are unavailable: test input method setup timed out", flush=True)
                except (OSError, RuntimeError) as error:
                    print(f"Android Unicode and clipboard are unavailable: {error}", flush=True)
                else:
                    self.ime = ime
        else:
            requested = os.environ.get("UI_TEST_DEVICE", "")
            if self.legacy is None and requested:
                from uuid import UUID
                self.device = str(UUID(requested)).upper()
            else:
                booted = json.loads(_run("xcrun", "simctl", "list", "devices", "booted", "-j", timeout=40))
                available = [
                    item["udid"] for runtime, devices in booted["devices"].items()
                    if ".iOS-" in runtime for item in devices if item["state"] == "Booted"
                ]
                self.device = select_device(requested, available, "booted iOS simulator")

    def capabilities(self):
        commands = []
        if self.target == "android":
            commands.extend(("pointer.click", "pointer.drag", "pointer.scroll", "keyboard.press",
                             "tree.snapshot", "device.orientation"))
        if self.ime or self.target == "ios":
            commands.extend(("clipboard.get", "clipboard.set"))
            if self.legacy is not None:
                commands.append("text.insert")
        if self.app_ids:
            commands.extend(("app.launch", "app.close", "app.restart", "app.uninstall"))
            if self.target == "android" or self.install_paths:
                commands.append("app.reset")
        if self.install_paths:
            commands.append("app.install")
        if self.url_schemes:
            commands.append("app.deeplink")
        return commands

    def adb(self, *args, timeout=20):
        return _run(*self.legacy.adb, *args, timeout=timeout)

    def shell(self, *args, timeout=20):
        # adb passes this command to a remote POSIX shell.
        return self.adb("shell", " ".join(quote(item) for item in args), timeout=timeout)

    def simctl(self, command, *args, stdin=None, timeout=20):
        return _run("xcrun", "simctl", command, self.device, *args, stdin=stdin, timeout=timeout)

    def _require_simulator_focus(self):
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not app or str(app.bundleIdentifier()).lower() != "com.apple.iphonesimulator":
            raise CommandError("focus_required", "Click inside the iOS Simulator before sending text.", 409)

    def _clipboard(self, command, params):
        if self.ime:
            if command == "clipboard.get":
                return {"text": self.ime.execute(command)}
            self.ime.execute(command, params["text"])
            return {}
        if command == "clipboard.get":
            raw = self.simctl("pbpaste")
            if len(raw) > _MAX_TEXT_BYTES:
                raise RuntimeError("iOS pasteboard text exceeds 16 KiB")
            return {"text": raw.decode("utf-8")}
        self.simctl("pbcopy", stdin=_utf8(params["text"]))
        return {}

    def _text(self, params):
        entry = params["text"]
        if self.ime:
            self.ime.execute("text.replace" if params.get("replace") else "text.insert", entry)
            return {}
        self._require_simulator_focus()
        self.simctl("pbcopy", stdin=_utf8(entry))
        if params.get("replace"):
            self.legacy.gui.hotkey("command", "a")
        self.legacy.gui.hotkey("command", "v")
        return {}

    def _click(self, params):
        if params.get("button", "left") != "left":
            raise ValueError("Android touch supports the primary button only")
        x, y = str(params["x"]), str(params["y"])
        hold = params.get("hold_ms", 0)
        count = params.get("count", 1)
        if hold and count != 1:
            raise ValueError("Android touch cannot combine a hold with repeated taps")
        if hold:
            self.shell("input", "swipe", x, y, x, y, str(hold))
        elif count == 1:
            self.shell("input", "tap", x, y)
        else:
            # One on-device shell avoids an ADB network round-trip between taps.
            tap = f"input tap {quote(x)} {quote(y)}"
            self.adb("shell", " && ".join([tap] * count))
        return {}

    def _drag(self, params):
        if params.get("button", "left") != "left":
            raise ValueError("Android touch supports the primary button only")
        points = tuple(str(params[key]) for key in ("x", "y", "end_x", "end_y"))
        self.shell("input", "draganddrop", *points, str(params.get("duration_ms", 450)))
        return {}

    def _scroll(self, params):
        # A down/right scroll moves the finger up/left. Each unit represents a scroll increment.
        png = self.legacy.capture()
        width, height = struct.unpack_from(">II", png, 16)
        x, y = params["x"], params["y"]
        end_x = min(width - 1, max(0, x - params.get("dx", 0) * 24))
        end_y = min(height - 1, max(0, y - params.get("dy", 0) * 24))
        if (x, y) == (end_x, end_y):
            raise ValueError("Scroll starts too close to the screen edge or has no distance")
        self.shell("input", "swipe", str(x), str(y), str(end_x), str(end_y), "330")
        return {"end_x": end_x, "end_y": end_y}

    def _keys(self, params):
        keys = tuple(_key(key) for key in params["keys"])
        if len(keys) > 1:
            modifiers = {"KEYCODE_CTRL_LEFT", "KEYCODE_ALT_LEFT", "KEYCODE_SHIFT_LEFT", "KEYCODE_META_LEFT"}
            if any(key not in modifiers for key in keys[:-1]) or len(keys) != len(set(keys)):
                raise ValueError("A keyboard chord requires distinct modifiers followed by one key")
        self.shell("input", "keyevent" if len(keys) == 1 else "keycombination", *keys)
        return {}

    def _snapshot(self):
        path = f"/data/local/tmp/uitest-tree-{uuid.uuid4().hex}.xml"
        try:
            self.shell("uiautomator", "dump", path, timeout=14)
            return parse_android_tree(self.adb("exec-out", "cat", path, timeout=5))
        finally:
            try:
                self.shell("rm", "-f", path, timeout=3)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                pass

    def _orientation(self, params):
        orientation = params["orientation"]
        if orientation not in _ANDROID_ROTATIONS and orientation != "auto":
            raise ValueError("Android orientation requires a portrait or landscape direction, or auto")
        if self.previous_rotation is None:
            self.previous_rotation = [
                self.shell("settings", "get", "system", name).decode().strip()
                for name in ("accelerometer_rotation", "user_rotation")
            ]
        if orientation == "auto":
            self.shell("settings", "put", "system", "accelerometer_rotation", "1")
        else:
            self.shell("settings", "put", "system", "accelerometer_rotation", "0")
            self.shell("settings", "put", "system", "user_rotation", _ANDROID_ROTATIONS[orientation])
        return {"orientation": orientation}

    def _app_id(self, params):
        identifier = params.get("id")
        if identifier not in self.app_ids:
            raise ValueError("The requested app is outside this session's allowlist")
        return identifier

    def _app_install_path(self, identifier):
        path = self.install_paths.get(identifier)
        if not path:
            raise ValueError("No runner install path was configured for the requested app")
        artifact = Path(path).resolve(strict=True)
        if self.target == "android" and artifact.suffix.lower() == ".apk" and artifact.is_file():
            home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
            if not home:
                raise RuntimeError("ANDROID_HOME must point to the SDK to verify install artifacts")
            tools = Path(home) / "build-tools" / "35.0.0"
            manifest = _run(str(tools / "aapt"), "dump", "badging", str(artifact))
            if not manifest.startswith(f"package: name='{identifier}' ".encode()):
                raise ValueError("Configured APK package ID does not match the requested app")
            return str(artifact)
        if self.target == "ios" and artifact.suffix.lower() == ".app" and artifact.is_dir():
            with (artifact / "Info.plist").open("rb") as input_file:
                if plistlib.load(input_file).get("CFBundleIdentifier") != identifier:
                    raise ValueError("Configured Simulator app bundle ID does not match the requested app")
            return str(artifact)
        raise ValueError("Use a configured Android .apk file or iOS Simulator .app directory")

    def _install(self, identifier, artifact):
        if self.target == "android":
            self.adb("install", "-r", artifact, timeout=45)
        else:
            self.simctl("install", artifact, timeout=45)
        return {"id": identifier}

    def _android_app(self, command, identifier):
        if command == "app.reset":
            if self.shell("pm", "clear", identifier).strip() != b"Success":
                raise RuntimeError("Android app data could not be reset")
        elif command == "app.uninstall":
            self.adb("uninstall", identifier, timeout=30)
        else:
            if command in {"app.close", "app.restart"}:
                self.shell("am", "force-stop", identifier)
            if command in {"app.launch", "app.restart"}:
                output = self.shell("cmd", "package", "resolve-activity", "--brief", "-a",
                                    "android.intent.action.MAIN", "-c",
                                    "android.intent.category.LAUNCHER", "-p", identifier).decode().splitlines()
                component = next((line for line in reversed(output) if line.startswith(identifier + "/")), None)
                if not component:
                    raise RuntimeError("Android app has no resolved launcher activity")
                if b"Status: ok" not in self.shell("am", "start", "-W", "-n", component):
                    raise RuntimeError("Android launcher activity did not start")
        return {"id": identifier}

    def _ios_app(self, command, identifier):
        if command == "app.reset":
            artifact = self._app_install_path(identifier)
            self.simctl("uninstall", identifier)
            return self._install(identifier, artifact)
        if command == "app.restart":
            _run("xcrun", "simctl", "launch", "--terminate-running-process", self.device, identifier)
        else:
            self.simctl({"app.launch": "launch", "app.close": "terminate",
                         "app.uninstall": "uninstall"}[command], identifier)
        return {"id": identifier}

    def _open_url(self, params):
        url = params["url"]
        if not isinstance(url, str) or len(url) > 4096 or re.search(r"[\x00-\x20\x7f]", url):
            raise ValueError("URL must be a single encoded URI of no more than 4096 characters")
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in self.url_schemes or not (parsed.netloc or parsed.path):
            raise ValueError("URL scheme is outside this session's allowlist")
        if self.target == "ios":
            if "id" in params:
                raise ValueError("iOS deep links are dispatched by the Simulator to the registered app")
            self.simctl("openurl", url)
        else:
            intent = ["am", "start", "-W", "-a", "android.intent.action.VIEW", "-d", url]
            if "id" in params:
                intent.extend(("-p", self._app_id(params)))
            if b"Status: ok" not in self.shell(*intent):
                raise RuntimeError("Android could not resolve the configured deep link")
        return {}

    def execute(self, command, params):
        if command not in self.capabilities():
            raise NotImplementedError(f"{command} is unavailable on this mobile session")
        if command == "text.insert":
            return self._text(params)
        if command.startswith("clipboard."):
            return self._clipboard(command, params)
        if command == "app.deeplink":
            return self._open_url(params)
        if command.startswith("app."):
            identifier = self._app_id(params)
            if command == "app.install":
                return self._install(identifier, self._app_install_path(identifier))
            if self.target == "android":
                return self._android_app(command, identifier)
            return self._ios_app(command, identifier)
        if command == "tree.snapshot":
            return self._snapshot()
        handlers = {
            "pointer.click": self._click, "pointer.drag": self._drag, "pointer.scroll": self._scroll,
            "keyboard.press": self._keys, "device.orientation": self._orientation,
        }
        return handlers[command](params)

    def close(self):
        if self.target == "android":
            try:
                if self.previous_rotation is not None:
                    for name, value in zip(("accelerometer_rotation", "user_rotation"), self.previous_rotation):
                        if value == "null":
                            self.shell("settings", "delete", "system", name, timeout=3)
                        else:
                            self.shell("settings", "put", "system", name, value, timeout=3)
            finally:
                if self.ime:
                    self.ime.close()
