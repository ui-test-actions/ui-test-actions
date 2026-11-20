"""Native control for the interactive desktop in a hosted UI session."""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


MOUSE_BUTTONS = {"left": 1, "middle": 2, "right": 3}
POINTER_COMMANDS = ("pointer.move", "pointer.click", "pointer.drag", "pointer.scroll")
CLIPBOARD_COMMANDS = ("text.insert", "clipboard.get", "clipboard.set")
WINDOW_COMMANDS = ("windows.list", "windows.focus", "windows.move_resize", "windows.close")
MAX_CLIPBOARD_BYTES = 1024 * 1024

KEY_ALIASES = {
    "control": "ctrl", "command": "meta", "cmd": "meta", "win": "meta", "super": "meta",
    "option": "alt", "escape": "esc", "return": "enter",
    "arrowleft": "left", "arrowright": "right", "arrowup": "up", "arrowdown": "down",
    "page-up": "pageup", "page-down": "pagedown", "del": "delete", "spacebar": "space",
    "minus": "-", "equal": "=", "leftbracket": "[", "rightbracket": "]", "backslash": "\\",
    "semicolon": ";", "apostrophe": "'", "comma": ",", "period": ".", "slash": "/", "backtick": "`",
}
X11_KEYS = {
    "ctrl": "Control_L", "alt": "Alt_L", "shift": "Shift_L", "meta": "Super_L",
    "esc": "Escape", "enter": "Return", "tab": "Tab", "space": "space",
    "backspace": "BackSpace", "delete": "Delete", "insert": "Insert", "home": "Home",
    "end": "End", "pageup": "Page_Up", "pagedown": "Page_Down", "left": "Left",
    "up": "Up", "right": "Right", "down": "Down", "capslock": "Caps_Lock",
    "menu": "Menu", "printscreen": "Print", "pause": "Pause", "scrolllock": "Scroll_Lock",
    "numlock": "Num_Lock", "-": "minus", "=": "equal", "[": "bracketleft",
    "]": "bracketright", "\\": "backslash", ";": "semicolon", "'": "apostrophe",
    ",": "comma", ".": "period", "/": "slash", "`": "grave",
}
MAC_KEYS = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28,
    "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "enter": 36, "l": 37,
    "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46,
    ".": 47, "tab": 48, "space": 49, "`": 50, "backspace": 51, "esc": 53, "meta": 55,
    "shift": 56, "capslock": 57, "alt": 58, "ctrl": 59, "f17": 64, "f18": 79,
    "f19": 80, "f20": 90, "f5": 96, "f6": 97, "f7": 98, "f3": 99, "f8": 100,
    "f9": 101, "f11": 103, "f13": 105, "f16": 106, "f14": 107, "f10": 109,
    "f12": 111, "f15": 113, "insert": 114, "home": 115, "pageup": 116, "delete": 117,
    "f4": 118, "end": 119, "f2": 120, "pagedown": 121, "f1": 122, "left": 123,
    "right": 124, "down": 125, "up": 126,
}
WINDOWS_KEYS = {"meta": "winleft", "menu": "apps", "printscreen": "printscreen"}
MODIFIERS = ("ctrl", "alt", "shift", "meta")


def os_command(*args, timeout=12, input_data=None, env=None, read=True):
    try:
        return subprocess.run(
            args, input=input_data, check=True, timeout=timeout, env=env,
            stdout=subprocess.PIPE if read else subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"{Path(args[0]).name} failed with status {error.returncode}") from None
    except subprocess.TimeoutExpired:
        raise subprocess.TimeoutExpired(Path(args[0]).name, timeout) from None


def box(x, y, width, height):
    return {"x": int(x), "y": int(y), "width": int(width), "height": int(height)}


class DesktopDriver:
    def __init__(self, legacy, target):
        self.legacy = legacy
        self.target = target
        self.win = WindowsDesktop() if target == "windows" else None
        self.x11_clipboard = target == "linux" and shutil.which("xclip") is not None
        self.x11_windows = target == "linux" and shutil.which("wmctrl") is not None
        if self.x11_windows:
            try:
                os_command("wmctrl", "-m", timeout=2)
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                self.x11_windows = False
        self.x11_tree = (
            target == "linux" and bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
            and Path("/usr/lib/python3/dist-packages/pyatspi").is_dir()
        )
        self.ax = None
        if target == "macos":
            try:
                from ApplicationServices import AXIsProcessTrusted
                if AXIsProcessTrusted():
                    self.ax = MacAccessibility()
            except (ImportError, AttributeError, OSError):
                pass

    def capabilities(self):
        supported = [*POINTER_COMMANDS, "keyboard.press"]
        if self.target in ("windows", "macos") or self.x11_clipboard:
            supported.extend(CLIPBOARD_COMMANDS)
        if self.target == "windows" or self.ax or self.x11_windows:
            supported.extend(WINDOW_COMMANDS)
        if self.target == "windows" or self.ax or self.x11_tree:
            supported.append("tree.snapshot")
        return supported

    def execute(self, command, params):
        if command not in self.capabilities():
            raise NotImplementedError("Command is unavailable on this desktop")
        match command:
            case "pointer.move":
                self.move((params["x"], params["y"]), params.get("duration_ms", 0))
            case "pointer.click":
                self.click(params)
            case "pointer.drag":
                self.drag(params)
            case "pointer.scroll":
                self.scroll(params)
            case "keyboard.press":
                self.press(params["keys"])
            case "clipboard.get":
                return {"text": self.clipboard_read()}
            case "clipboard.set":
                self.clipboard_write(params["text"])
            case "text.insert":
                self.insert(params["text"], params.get("replace", False))
            case "tree.snapshot":
                return self.tree()
            case "windows.list":
                return {"windows": self.windows()}
            case "windows.focus" | "windows.move_resize" | "windows.close":
                self.window_action(command, params)
        return {}

    def cursor(self):
        if self.target == "linux":
            output = os_command("xdotool", "getmouselocation", "--shell").decode("ascii")
            position = dict(line.split("=", 1) for line in output.splitlines())
            return int(position["X"]), int(position["Y"])
        if self.win:
            x, y = self.legacy.gui.position()
            return x, y
        q = self.legacy.quartz
        location = q.CGEventGetLocation(q.CGEventCreate(None))
        return round(location.x), round(location.y)

    def move(self, end, ms=0, held=None, start=None):
        if not ms:
            self.mouse_event("move", end, held)
            return
        if start is None:
            start = self.cursor()
        x1, y1 = start
        x2, y2 = end
        duration = ms / 1000
        steps = min(48, math.ceil(duration * 40))
        mark = time.monotonic()
        for step in range(1, steps + 1):
            position = (round(x1 + (x2 - x1) * step / steps), round(y1 + (y2 - y1) * step / steps))
            time.sleep(max(0, mark + duration * step / steps - time.monotonic()))
            self.mouse_event("move", position, held)

    def click(self, params):
        point = (params["x"], params["y"])
        button = params.get("button", "left")
        count = params.get("count", 1)
        hold = params.get("hold_ms", 0) / 1000
        self.move(point)
        for index in range(count):
            self.mouse_event("down", point, button, index + 1)
            try:
                if hold:
                    time.sleep(hold)
            finally:
                self.mouse_event("up", point, button, index + 1)
            if index + 1 < count:
                time.sleep(0.05)

    def drag(self, params):
        start = (params["x"], params["y"])
        end = (params["end_x"], params["end_y"])
        button = params.get("button", "left")
        self.move(start)
        self.mouse_event("down", start, button)
        try:
            self.move(end, params.get("duration_ms", 400), held=button, start=start)
        finally:
            self.mouse_event("up", end, button)

    def mouse_event(self, action, point, button=None, count=1):
        x, y = point
        if self.target == "linux":
            args = ("mousemove", str(x), str(y)) if action == "move" else ("mouse" + action, str(MOUSE_BUTTONS[button]))
            os_command("xdotool", *args, read=False)
            return
        if self.win:
            if action == "move":
                self.legacy.gui.moveTo(x, y, _pause=False)
            else:
                getattr(self.legacy.gui, "mouse" + action.title())(x, y, button=button, _pause=False)
            return
        q = self.legacy.quartz
        event_button, prefix = {
            "left": (q.kCGMouseButtonLeft, "Left"), "right": (q.kCGMouseButtonRight, "Right"),
            "middle": (q.kCGMouseButtonCenter, "Other"),
        }[button or "left"]
        if action == "move":
            event_name = f"kCGEvent{prefix}MouseDragged" if button else "kCGEventMouseMoved"
        else:
            event_name = f"kCGEvent{prefix}Mouse{action.title()}"
        event = q.CGEventCreateMouseEvent(None, getattr(q, event_name), point, event_button)
        q.CGEventSetIntegerValueField(event, q.kCGMouseEventClickState, count)
        q.CGEventPost(q.kCGHIDEventTap, event)

    def scroll(self, params):
        self.move((params["x"], params["y"]))
        dx, dy = params.get("dx", 0), params.get("dy", 0)
        if self.target == "linux":
            for delta, positive, negative in ((dy, 5, 4), (dx, 7, 6)):
                if delta:
                    os_command(
                        "xdotool", "click", "--repeat", str(abs(delta)), "--delay", "0",
                        str(positive if delta > 0 else negative), read=False,
                    )
        elif self.win:
            self.win.scroll(dx, dy)
        else:
            q = self.legacy.quartz
            q.CGEventPost(q.kCGHIDEventTap, q.CGEventCreateScrollWheelEvent(None, q.kCGScrollEventUnitLine, 2, -dy, -dx))

    def press(self, requested):
        keys = [KEY_ALIASES.get(key.lower(), key.lower()) for key in requested]
        if len(keys) != len(set(keys)):
            raise ValueError("A key cannot appear twice in one chord")
        keys.sort(key=lambda key: key not in MODIFIERS)
        if self.target == "linux":
            names = []
            for key in keys:
                if key in X11_KEYS:
                    names.append(X11_KEYS[key])
                elif re.fullmatch(r"[a-z0-9]", key):
                    names.append(key)
                elif re.fullmatch(r"f(?:[1-9]|1[0-9]|2[0-4])", key):
                    names.append(key.upper())
                else:
                    raise ValueError("Unknown key for X11")
            os_command("xdotool", "key", "--clearmodifiers", "+".join(names), read=False)
        elif self.win:
            names = [WINDOWS_KEYS.get(key, key) for key in keys]
            gui = self.legacy.gui
            if any(not gui.isValidKey(key) for key in names):
                raise ValueError("Unknown key for Windows")
            held = []
            try:
                for name in names:
                    gui.keyDown(name, _pause=False)
                    held.append(name)
            finally:
                for name in reversed(held):
                    gui.keyUp(name, _pause=False)
        else:
            self.mac_press(keys)

    def mac_press(self, keys):
        if any(key not in MAC_KEYS for key in keys):
            raise ValueError("Unknown key for macOS")
        q = self.legacy.quartz
        mask = {
            "ctrl": q.kCGEventFlagMaskControl, "alt": q.kCGEventFlagMaskAlternate,
            "shift": q.kCGEventFlagMaskShift, "meta": q.kCGEventFlagMaskCommand,
        }
        held = []

        def post(key, down):
            flags = 0
            for current in held:
                flags |= mask.get(current, 0)
            event = q.CGEventCreateKeyboardEvent(None, MAC_KEYS[key], down)
            q.CGEventSetFlags(event, flags)
            q.CGEventPost(q.kCGHIDEventTap, event)

        try:
            for key in keys:
                held.append(key)
                post(key, True)
                time.sleep(0.015)
        finally:
            while held:
                post(held.pop(), False)
                time.sleep(0.015)

    def insert(self, text, replace):
        if replace:
            self.press(["meta" if self.target == "macos" else "ctrl", "a"])
        if text:
            self.clipboard_write(text)
            self.press(["meta" if self.target == "macos" else "ctrl", "v"])
        elif replace:
            self.press(["backspace"])

    def clipboard_read(self):
        if self.win:
            return self.win.clipboard_read()
        if self.target == "linux":
            output = os_command("xclip", "-selection", "clipboard", "-o", "-t", "UTF8_STRING")
        else:
            output = os_command("pbpaste", env={**os.environ, "LC_ALL": "en_US.UTF-8"})
        if len(output) > MAX_CLIPBOARD_BYTES:
            raise RuntimeError("Clipboard text exceeds the session size limit")
        if self.target == "linux":
            # Tk 8.6 can export paired UTF-16 surrogates in X11 UTF8_STRING.
            # Combine adjacent valid pairs and reject other malformed text.
            return output.decode("utf-8", "surrogatepass").encode("utf-16-le", "surrogatepass").decode("utf-16-le")
        return output.decode("utf-8")

    def clipboard_write(self, text):
        if "\x00" in text:
            raise ValueError("Clipboard text cannot contain NUL")
        if len(text.encode("utf-8")) > MAX_CLIPBOARD_BYTES:
            raise ValueError("Clipboard text exceeds the session size limit")
        if self.win:
            self.win.clipboard_write(text)
        elif self.target == "linux":
            os_command("xclip", "-selection", "clipboard", "-i", "-t", "UTF8_STRING", input_data=text.encode(), read=False)
        else:
            os_command("pbcopy", input_data=text.encode(), env={**os.environ, "LC_ALL": "en_US.UTF-8"}, read=False)

    def windows(self):
        if self.win:
            return self.win.windows()
        if self.ax:
            return self.ax.windows()
        listing = os_command("wmctrl", "-lpG").decode("utf-8", errors="replace")
        result = []
        for row in listing.splitlines():
            values = row.split(maxsplit=8)
            if len(values) >= 8:
                window_id, _desktop, pid, x, y, width, height, _host, *title = values
                if int(pid) <= 0:
                    # Some clients omit _NET_WM_PID; their X11 window remains addressable.
                    pid = "0"
                result.append({
                    "id": window_id, "process_id": int(pid), "title": title[0] if title else "",
                    "bounds": box(x, y, width, height),
                })
        return result

    def window_action(self, command, params):
        if self.win:
            self.win.window_action(command, params)
            return
        if self.ax:
            self.ax.window_action(command, params)
            return
        window_id = params["id"]
        if not re.fullmatch(r"0x[0-9a-fA-F]{1,8}", window_id):
            raise ValueError("Invalid X11 window ID")
        if not any(window["id"] == window_id for window in self.windows()):
            raise LookupError("Window is no longer available")
        if command == "windows.focus":
            os_command("wmctrl", "-ia", window_id, read=False)
        elif command == "windows.close":
            os_command("wmctrl", "-ic", window_id, read=False)
        else:
            values = ",".join(str(params[key]) for key in ("x", "y", "width", "height"))
            os_command("wmctrl", "-ir", window_id, "-e", "0," + values, read=False)

    def tree(self):
        if self.win:
            encoded = os_command(
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_TREE, timeout=14,
            )
            return json.loads(encoded.decode("utf-8-sig"))
        if self.ax:
            return self.ax.tree()
        encoded = os_command("/usr/bin/python3", str(Path(__file__).resolve()), "--atspi", timeout=14)
        return json.loads(encoded.decode("utf-8"))


class WindowsDesktop:
    def __init__(self):
        wt = wintypes
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.memory = ctypes.WinDLL("kernel32", use_last_error=True)
        self.enum_callback = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        signatures = (
            (self.user, "OpenClipboard", wt.BOOL, wt.HWND),
            (self.user, "CloseClipboard", wt.BOOL),
            (self.user, "EmptyClipboard", wt.BOOL),
            (self.user, "GetClipboardData", wt.HANDLE, wt.UINT),
            (self.user, "SetClipboardData", wt.HANDLE, wt.UINT, wt.HANDLE),
            (self.user, "IsClipboardFormatAvailable", wt.BOOL, wt.UINT),
            (self.user, "CreateWindowExW", wt.HWND, wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID),
            (self.user, "DestroyWindow", wt.BOOL, wt.HWND),
            (self.user, "EnumWindows", wt.BOOL, self.enum_callback, wt.LPARAM),
            (self.user, "IsWindowVisible", wt.BOOL, wt.HWND),
            (self.user, "GetWindowTextLengthW", ctypes.c_int, wt.HWND),
            (self.user, "GetWindowTextW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int),
            (self.user, "GetWindowRect", wt.BOOL, wt.HWND, ctypes.POINTER(wt.RECT)),
            (self.user, "GetWindowThreadProcessId", wt.DWORD, wt.HWND, ctypes.POINTER(wt.DWORD)),
            (self.user, "ShowWindow", wt.BOOL, wt.HWND, ctypes.c_int),
            (self.user, "SetForegroundWindow", wt.BOOL, wt.HWND),
            (self.user, "MoveWindow", wt.BOOL, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.BOOL),
            (self.user, "PostMessageW", wt.BOOL, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM),
            (self.user, "mouse_event", None, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t),
            (self.memory, "GetModuleHandleW", wt.HMODULE, wt.LPCWSTR),
            (self.memory, "GlobalAlloc", wt.HGLOBAL, wt.UINT, ctypes.c_size_t),
            (self.memory, "GlobalFree", wt.HGLOBAL, wt.HGLOBAL),
            (self.memory, "GlobalLock", wt.LPVOID, wt.HGLOBAL),
            (self.memory, "GlobalUnlock", wt.BOOL, wt.HGLOBAL),
            (self.memory, "GlobalSize", ctypes.c_size_t, wt.HGLOBAL),
        )
        for library, name, returns, *types in signatures:
            function = getattr(library, name)
            function.restype = returns
            function.argtypes = types

    @contextmanager
    def clipboard(self):
        owner = self.user.CreateWindowExW(
            0, "Static", "", 0, 0, 0, 0, 0, None, None, self.memory.GetModuleHandleW(None), None,
        )
        if not owner:
            raise OSError("Could not create the Windows clipboard owner")
        try:
            deadline = time.monotonic() + 0.5
            while not self.user.OpenClipboard(owner):
                if time.monotonic() >= deadline:
                    raise OSError("The Windows clipboard is busy")
                time.sleep(0.025)
            try:
                yield
            finally:
                self.user.CloseClipboard()
        finally:
            self.user.DestroyWindow(owner)

    @contextmanager
    def global_buffer(self, handle):
        pointer = self.memory.GlobalLock(handle)
        if not pointer:
            raise OSError("Could not lock clipboard memory")
        try:
            yield pointer
        finally:
            self.memory.GlobalUnlock(handle)

    def clipboard_read(self):
        cf_unicode_text = 13
        with self.clipboard():
            if not self.user.IsClipboardFormatAvailable(cf_unicode_text):
                return ""
            handle = self.user.GetClipboardData(cf_unicode_text)
            if not handle:
                raise OSError("Could not read the Windows clipboard")
            size = self.memory.GlobalSize(handle)
            if size > 2 * MAX_CLIPBOARD_BYTES + 1024:
                raise RuntimeError("Clipboard text exceeds the session size limit")
            with self.global_buffer(handle) as pointer:
                data = ctypes.string_at(pointer, size - size % 2)
        end = next((i for i, unit in enumerate(memoryview(data).cast("H")) if not unit), None)
        if end is None:
            raise OSError("Windows clipboard text is missing its terminator")
        return data[:2 * end].decode("utf-16-le").replace("\r\n", "\n")

    def clipboard_write(self, text):
        cf_unicode_text = 13
        moveable = 0x0002
        native = text.replace("\r\n", "\n").replace("\n", "\r\n")
        data = (native + "\x00").encode("utf-16-le")
        handle = self.memory.GlobalAlloc(moveable, len(data))
        if not handle:
            raise OSError("Could not allocate clipboard memory")
        try:
            with self.global_buffer(handle) as pointer:
                ctypes.memmove(pointer, data, len(data))
            with self.clipboard():
                if not self.user.EmptyClipboard() or not self.user.SetClipboardData(cf_unicode_text, handle):
                    raise OSError("Could not update the Windows clipboard")
                handle = None
        finally:
            if handle:
                self.memory.GlobalFree(handle)

    def scroll(self, dx, dy):
        for flags, delta in ((0x0800, -dy), (0x1000, dx)):
            if delta:
                self.user.mouse_event(flags, 0, 0, (delta * 120) & 0xffffffff, 0)

    def windows(self):
        result = []

        @self.enum_callback
        def collect(window, _):
            if not self.user.IsWindowVisible(window):
                return True
            length = self.user.GetWindowTextLengthW(window)
            if not length:
                return True
            title = ctypes.create_unicode_buffer(min(length, 2048) + 1)
            self.user.GetWindowTextW(window, title, len(title))
            rect = wintypes.RECT()
            if not self.user.GetWindowRect(window, ctypes.byref(rect)):
                return True
            pid = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(window, ctypes.byref(pid))
            result.append({
                "id": f"0x{window:x}", "title": title.value, "process_id": pid.value,
                "bounds": box(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
            })
            return len(result) < 100

        self.user.EnumWindows(collect, 0)
        return result

    def window_action(self, command, params):
        window_id = params["id"]
        if not re.fullmatch(r"0x[0-9a-fA-F]{1,16}", window_id):
            raise ValueError("Invalid Windows window ID")
        handle = int(window_id, 16)
        if not any(int(window["id"], 16) == handle for window in self.windows()):
            raise LookupError("Window is no longer available")
        if command == "windows.focus":
            self.user.ShowWindow(handle, 9)  # SW_RESTORE
            result = self.user.SetForegroundWindow(handle)
        elif command == "windows.close":
            result = self.user.PostMessageW(handle, 0x0010, 0, 0)  # WM_CLOSE
        else:
            result = self.user.MoveWindow(handle, params["x"], params["y"], params["width"], params["height"], True)
        if not result:
            raise OSError("Windows refused the window operation")


WINDOWS_TREE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$elementType = [System.Windows.Automation.AutomationElement]
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$desktop = $elementType::RootElement
$root = $elementType::FocusedElement
while ($root) {
    $parent = $walker.GetParent($root)
    if (-not $parent -or [System.Windows.Automation.Automation]::Compare($parent, $desktop)) { break }
    $root = $parent
}
$nodes = [System.Collections.Generic.List[object]]::new()
$queue = [System.Collections.Queue]::new()
if ($root) { $queue.Enqueue($root) }
$limit = 300
$truncated = $false
while ($queue.Count -gt 0 -and $nodes.Count -lt $limit) {
    $element = $queue.Dequeue()
    try {
        $current = $element.Current
        $role = $current.ControlType.ProgrammaticName.Split('.')[-1].ToLowerInvariant()
        $rect = $current.BoundingRectangle
        $bounds = $null
        if (-not $rect.IsEmpty -and $rect.Width -gt 0 -and $rect.Height -gt 0) {
            $bounds = @{x = [int]$rect.X; y = [int]$rect.Y; width = [int]$rect.Width; height = [int]$rect.Height}
        }
        $name = [string]$current.Name
        $value = ''
        if ($current.IsPassword) {
            $name = ''
        } else {
            try {
                $pattern = $null
                if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) {
                    $value = [string]$pattern.Current.Value
                } elseif ($element.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$pattern)) {
                    $value = [string]$pattern.DocumentRange.GetText(2048)
                }
            } catch {}
        }
        if ($value.Length -gt 2048) { $value = $value.Substring(0, 2048) }
        if ($name.Length -gt 512) { $name = $name.Substring(0, 512) }
        $identity = $element.GetRuntimeId() -join '.'
        $nodes.Add(@{
            id = "win:$($current.ProcessId):$identity"; role = $role; name = $name; text = $value
            enabled = $current.IsEnabled; visible = -not $current.IsOffscreen; bounds = $bounds
        })
        if (-not $current.IsPassword) {
            $child = $walker.GetFirstChild($element)
            while ($child -and $nodes.Count + $queue.Count -lt $limit) {
                $queue.Enqueue($child)
                $child = $walker.GetNextSibling($child)
            }
            if ($child) { $truncated = $true }
        }
    } catch [System.Windows.Automation.ElementNotAvailableException] {}
}
ConvertTo-Json -InputObject @{nodes = @($nodes.ToArray()); truncated = [bool]($truncated -or $queue.Count -gt 0)} -Depth 5 -Compress
"""


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _Size(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class MacAccessibility:
    def __init__(self):
        import AppKit
        import ApplicationServices
        import objc

        self.ax = ApplicationServices
        self.appkit = AppKit
        self.objc = objc
        self.known_windows = {}
        self.native = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        self.native.AXValueGetValue.restype = ctypes.c_bool
        self.native.AXValueGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        self.native.AXValueCreate.restype = ctypes.c_void_p
        self.native.AXValueCreate.argtypes = [ctypes.c_int, ctypes.c_void_p]
        self.native.AXUIElementSetAttributeValue.restype = ctypes.c_int
        self.native.AXUIElementSetAttributeValue.argtypes = [ctypes.c_void_p] * 3
        self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        self.cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        self.cf.CFRelease.restype = None
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]

    def app(self, pid):
        app = self.ax.AXUIElementCreateApplication(pid)
        self.ax.AXUIElementSetMessagingTimeout(app, 0.3)
        return app

    def value(self, element, name):
        code, result = self.ax.AXUIElementCopyAttributeValue(element, name, None)
        return result if code == 0 else None

    def bounds(self, element):
        position = self.value(element, "AXPosition")
        size = self.value(element, "AXSize")
        if position is None or size is None:
            return None
        coordinates = _Point()
        dimensions = _Size()
        if not self.native.AXValueGetValue(self.objc.pyobjc_id(position), 1, ctypes.byref(coordinates)):
            return None
        if not self.native.AXValueGetValue(self.objc.pyobjc_id(size), 2, ctypes.byref(dimensions)):
            return None
        if not all(math.isfinite(n) for n in (coordinates.x, coordinates.y, dimensions.width, dimensions.height)):
            return None
        return box(coordinates.x, coordinates.y, dimensions.width, dimensions.height)

    def string(self, element, attribute, limit):
        value = self.value(element, attribute)
        return str(value)[:limit] if isinstance(value, str) else ""

    def tree(self):
        with self.objc.autorelease_pool():
            foreground = self.appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
            if foreground is None:
                return {"nodes": [], "truncated": False}
            pid = foreground.processIdentifier()
            app = self.app(pid)
            root = self.value(app, "AXFocusedWindow") or app
            deadline = time.monotonic() + 8
            stack = [("0", root)]
            nodes = []
            truncated = False
            while stack and len(nodes) < 300 and time.monotonic() < deadline:
                key, item = stack.pop()
                role = self.string(item, "AXRole", 128)
                secure = role == "AXSecureTextField" or self.value(item, "AXSubrole") == "AXSecureTextField"
                bounds = self.bounds(item)
                enabled = self.value(item, "AXEnabled")
                nodes.append({
                    "id": f"mac:{pid}:{key}", "role": role.removeprefix("AX").lower(),
                    "name": "" if secure else (
                        self.string(item, "AXTitle", 512) or self.string(item, "AXDescription", 512)
                    ),
                    "text": "" if secure else self.string(item, "AXValue", 2048),
                    "enabled": True if enabled is None else bool(enabled),
                    "visible": bounds is not None and not bool(self.value(item, "AXHidden")),
                    "bounds": bounds,
                })
                if not secure:
                    children = self.value(item, "AXChildren") or ()
                    available = 300 - len(nodes) - len(stack)
                    truncated = truncated or len(children) > available
                    stack.extend((f"{key}.{i}", child) for i, child in reversed(list(enumerate(children[:available]))))
            return {"nodes": nodes, "truncated": truncated or bool(stack)}

    def windows(self):
        result = []
        self.known_windows.clear()
        deadline = time.monotonic() + 8
        with self.objc.autorelease_pool():
            for program in self.appkit.NSWorkspace.sharedWorkspace().runningApplications():
                if program.activationPolicy() != self.appkit.NSApplicationActivationPolicyRegular:
                    continue
                if time.monotonic() >= deadline or len(result) >= 100:
                    break
                pid = program.processIdentifier()
                for window in self.value(self.app(pid), "AXWindows") or ():
                    if time.monotonic() >= deadline or len(result) >= 100:
                        break
                    identifier = f"mac:{pid}:{hash(window) & 0xffffffffffffffff:x}"
                    self.known_windows[identifier] = (pid, window)
                    result.append({
                        "id": identifier, "process_id": pid, "title": self.string(window, "AXTitle", 512),
                        "bounds": self.bounds(window),
                    })
        return result

    def set_dimensions(self, window, name, kind, coordinates):
        value = self.native.AXValueCreate(kind, ctypes.byref(coordinates))
        if not value:
            raise OSError("macOS refused the window geometry")
        try:
            name_ref = self.cf.CFStringCreateWithCString(None, name.encode("ascii"), 0x08000100)
            if not name_ref:
                raise OSError("Could not allocate the macOS accessibility attribute")
            try:
                code = self.native.AXUIElementSetAttributeValue(self.objc.pyobjc_id(window), name_ref, value)
            finally:
                self.cf.CFRelease(name_ref)
        finally:
            self.cf.CFRelease(value)
        if code != 0:
            raise OSError("macOS refused the window geometry")

    def window_action(self, command, params):
        with self.objc.autorelease_pool():
            data = self.known_windows.get(params["id"])
            if not data or self.value(data[1], "AXRole") != "AXWindow":
                raise LookupError("Window is no longer available")
            pid, window = data
            if command == "windows.focus":
                application = self.appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                if application is None:
                    raise LookupError("Window is no longer available")
                application.activateWithOptions_(self.appkit.NSApplicationActivateIgnoringOtherApps)
                code = self.ax.AXUIElementPerformAction(window, "AXRaise")
            elif command == "windows.close":
                button = self.value(window, "AXCloseButton")
                if button is None:
                    raise OSError("Window has no accessibility close button")
                code = self.ax.AXUIElementPerformAction(button, "AXPress")
            else:
                self.set_dimensions(window, "AXSize", 2, _Size(params["width"], params["height"]))
                self.set_dimensions(window, "AXPosition", 1, _Point(params["x"], params["y"]))
                return
            if code != 0:
                raise OSError("macOS refused the window operation")


def linux_tree():
    from collections import deque

    import pyatspi

    roots = []
    try:
        desktop = pyatspi.Registry.getDesktop(0)
        for app in desktop:
            for window in app:
                if window.getState().contains(pyatspi.STATE_SHOWING):
                    roots.append(window)
    except Exception:
        raise RuntimeError("Could not query the Linux accessibility bus") from None
    active = [window for window in roots if window.getState().contains(pyatspi.STATE_ACTIVE)]
    if active:
        roots = active
    queue = deque((str(i), item) for i, item in enumerate(roots))
    nodes = []
    truncated = False
    limit = 300
    # Visit the editor and sibling controls before large nested menu trees.
    while queue and len(nodes) < limit:
        path, item = queue.popleft()
        try:
            state = item.getState()
            role = item.getRoleName()
            protected = item.getRole() == pyatspi.ROLE_PASSWORD_TEXT
            values = {
                "id": "atspi:" + path, "role": role, "name": "" if protected else (item.name or "")[:512],
                "parent_id": "atspi:" + path.rsplit(".", 1)[0] if "." in path else None,
                "text": "", "enabled": state.contains(pyatspi.STATE_ENABLED),
                "visible": state.contains(pyatspi.STATE_SHOWING), "bounds": None,
                "properties": {
                    "focused": state.contains(pyatspi.STATE_FOCUSED),
                    "selected": state.contains(pyatspi.STATE_SELECTED),
                    "checked": state.contains(pyatspi.STATE_CHECKED),
                    "editable": state.contains(pyatspi.STATE_EDITABLE),
                    "password": protected,
                },
            }
            try:
                rect = item.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
                if values["visible"] and rect.width > 0 and rect.height > 0:
                    values["bounds"] = box(rect.x, rect.y, rect.width, rect.height)
            except Exception:
                pass
            if not protected:
                try:
                    component = item.queryText()
                    values["text"] = component.getText(0, min(component.characterCount, 2048))
                except Exception:
                    pass
                room = limit - len(nodes) - len(queue) - 1
                count = min(max(0, room), item.childCount)
                truncated = truncated or count < item.childCount
                queue.extend((f"{path}.{i}", item[i]) for i in range(count))
            nodes.append(values)
        except Exception:
            # A dynamic application can remove a node while the tree is being read.
            continue
    return {"nodes": nodes, "truncated": truncated or bool(queue)}


if __name__ == "__main__":
    import sys

    if sys.argv[1:] != ["--atspi"]:
        sys.exit("Expected --atspi")
    print(json.dumps(linux_tree(), ensure_ascii=True))
