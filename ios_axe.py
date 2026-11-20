"""Optional, typed access to a runner-local AXe Simulator bridge."""

from collections import deque
from io import BytesIO
import json
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

from contract import CommandError
from mobile_driver import _run


MODIFIERS = {"ctrl": 224, "control": 224, "shift": 225, "alt": 226, "option": 226,
             "cmd": 227, "command": 227, "meta": 227}
HID_KEYS = {letter: 4 + i for i, letter in enumerate("abcdefghijklmnopqrstuvwxyz")}
HID_KEYS.update({digit: 30 + i for i, digit in enumerate("1234567890")})
HID_KEYS.update({
    "enter": 40, "return": 40, "escape": 41, "esc": 41, "backspace": 42, "tab": 43, "space": 44,
    "home": 74, "pageup": 75, "delete": 76, "end": 77, "pagedown": 78, "right": 79, "left": 80,
    "down": 81, "up": 82,
})


def frame(node):
    geometry = node.get("frame")
    if not isinstance(geometry, dict):
        return None
    values = [geometry.get(key) for key in ("x", "y", "width", "height")]
    if not all(type(value) in (int, float) and isfinite(value) and abs(value) <= 32768 for value in values):
        return None
    x, y, width, height = map(round, values)
    return (x, y, width, height) if width > 0 and height > 0 else None


def source_tree(roots, viewport, limit=2500):
    width, height = viewport
    queue = deque((str(index), None, root) for index, root in enumerate(roots))
    nodes = []
    while queue and len(nodes) < limit:
        identifier, parent, item = queue.popleft()
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("type") or "")
        traits = item.get("traits") or []
        classification = " ".join(map(str, (role, item.get("type"), item.get("subrole"), traits))).lower()
        secure = "secure" in classification or "password" in classification
        name = item.get("AXLabel") or item.get("title")
        text = item.get("AXValue")
        bounds = frame(item)
        start_x, start_y = 0, 0
        end_x, end_y = 0, 0
        if bounds:
            x, y, w, h = bounds
            start_x, start_y = max(0, x), max(0, y)
            end_x, end_y = min(width, x + w), min(height, y + h)
        node = {
            "id": identifier, "parent_id": parent, "role": role,
            "name": name[:512] if isinstance(name, str) and not secure else "",
            "text": text[:2048] if isinstance(text, str) and not secure else "",
            "enabled": item.get("enabled") is not False,
            "visible": end_x > start_x and end_y > start_y,
            "properties": {"password": secure, "editable": "textfield" in classification or "textview" in classification},
        }
        if node["visible"]:
            node["bounds"] = {"x": start_x, "y": start_y, "width": end_x-start_x, "height": end_y-start_y}
        resource = item.get("AXUniqueId")
        if isinstance(resource, str) and resource and not secure:
            node["resource_id"] = resource[:256]
        nodes.append(node)
        if not secure and isinstance(item.get("children"), list):
            queue.extend((f"{identifier}.{index}", identifier, child) for index, child in enumerate(item["children"]))
    return {"nodes": nodes, "truncated": bool(queue)}


class AxeSimulator:
    def __init__(self, binary, mobile):
        path = Path(binary)
        if not path.is_absolute() or not path.is_file():
            raise ValueError("ios-axe-path must name a runner-local AXe executable by absolute path.")
        self.binary = str(path)
        self.mobile = mobile
        self.viewport = None
        self.capture_size = None

    def capabilities(self):
        return set(self.mobile.capabilities()) | {
            "tree.snapshot", "pointer.click", "pointer.drag", "pointer.scroll", "keyboard.press", "text.insert",
        }

    def axe(self, *args):
        return _run(self.binary, *args, "--udid", self.mobile.device)

    def observe(self):
        source = self.axe("describe-ui")
        if len(source) > 4_000_000:
            raise RuntimeError("The AXe observation exceeded the size limit.")
        roots = json.loads(source)
        if not isinstance(roots, list) or not roots or not isinstance(roots[0], dict):
            raise RuntimeError("AXe did not return an application observation.")
        return roots

    def capture(self):
        from PIL import Image

        with TemporaryDirectory(prefix="ios-ui-capture-") as directory:
            capture = Path(directory) / "screen.png"
            _run("xcrun", "simctl", "io", self.mobile.device, "screenshot", "--type=png", str(capture), timeout=25)
            with Image.open(capture) as image:
                if image.size != self.capture_size:
                    root_size = frame(self.observe()[0])
                    if root_size is None or root_size[:2] != (0, 0):
                        raise RuntimeError("AXe did not report the geometry of the app viewport.")
                    width, height = root_size[2:]
                    if abs(image.width / width - image.height / height) > .04:
                        raise RuntimeError("The iOS screen and AXe viewport are out of alignment.")
                    self.viewport = (width, height)
                    self.capture_size = image.size
                scaled = image.resize(self.viewport, Image.Resampling.LANCZOS)
                output = BytesIO()
                scaled.save(output, "PNG")
                return output.getvalue()

    def key(self, keys):
        names = [key.lower() for key in keys]
        mods = [MODIFIERS[key] for key in names if key in MODIFIERS]
        keys = [HID_KEYS.get(key) for key in names if key not in MODIFIERS]
        if len(keys) != 1 or keys[0] is None or len(set(mods)) != len(mods):
            raise CommandError("invalid_arguments", "Use supported modifiers and exactly one iOS hardware key.")
        if mods:
            self.axe("key-combo", "--modifiers", ",".join(map(str, mods)), "--key", str(keys[0]))
        else:
            self.axe("key", str(keys[0]))

    def pointer(self, kind, points, duration):
        x, y = points[0]
        if kind == "click":
            return self.execute("pointer.click", {"x": x, "y": y})
        end_x, end_y = points[1]
        return self.execute("pointer.drag", {"x": x, "y": y, "end_x": end_x, "end_y": end_y,
                                            "duration_ms": round(duration * 1000)})

    def type_text(self, text):
        return self.execute("text.insert", {"text": text})

    def execute(self, command, params):
        if command == "tree.snapshot":
            return source_tree(self.observe(), self.viewport)
        if command == "text.insert":
            self.mobile.execute("clipboard.set", {"text": params["text"]})
            if params.get("replace"):
                self.key(["command", "a"])
            self.key(["command", "v"])
        elif command == "keyboard.press":
            self.key(params["keys"])
        elif command == "pointer.click":
            if params.get("button", "left") != "left":
                raise CommandError("invalid_arguments", "The AXe simulator uses touch input.")
            args = ["-x", str(params["x"]), "-y", str(params["y"])]
            if params.get("count", 1) > 1:
                args.extend(("--count", str(params["count"])))
            if params.get("hold_ms"):
                args.extend(("--hold", str(params["hold_ms"] / 1000)))
            self.axe("tap", *args)
        elif command in ("pointer.drag", "pointer.scroll"):
            if params.get("button", "left") != "left":
                raise CommandError("invalid_arguments", "The AXe simulator uses touch input.")
            x, y = params["x"], params["y"]
            if command == "pointer.scroll":
                width, height = self.viewport
                end_x = min(width - 1, max(0, x + params.get("dx", 0) * 64))
                end_y = min(height - 1, max(0, y + params.get("dy", 0) * 64))
            else:
                end_x, end_y = params["end_x"], params["end_y"]
            self.axe("draw", f"{x},{y}", f"{end_x},{end_y}",
                     "--duration", str(max(.1, params.get("duration_ms", 400) / 1000)))
        else:
            return self.mobile.execute(command, params)
        return {}

    def close(self):
        self.mobile.close()
