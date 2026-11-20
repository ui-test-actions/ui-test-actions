"""Optional loopback Appium adapter. Only typed automation routes reach Appium."""

import base64
import binascii
import http.client
import json
from math import isfinite
import re
from struct import unpack
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


MAX_DRIVER_RESPONSE = 16 * 1024 * 1024
PNG = b"\x89PNG\r\n\x1a\n"
SESSION = re.compile(r"[a-zA-Z0-9_.-]{1,128}")
BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


class WebDriverConnection:
    def __init__(self, endpoint):
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "::1")
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip("/") not in ("", "/wd/hub")
            or parsed.port is None or not 1024 <= parsed.port <= 65535
        ):
            raise ValueError("Appium must be configured on an explicit loopback HTTP address and port.")
        self.host, self.port, self.path = parsed.hostname, parsed.port, parsed.path.rstrip("/")

    def request(self, method, path, payload=None, timeout=20):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            content = json.dumps(payload).encode() if payload is not None else None
            connection.request(method, self.path + path, body=content, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read(MAX_DRIVER_RESPONSE + 1)
        except http.client.HTTPException:
            raise RuntimeError("Appium did not return a complete response.") from None
        finally:
            connection.close()
        if len(data) > MAX_DRIVER_RESPONSE or response.status >= 300:
            raise RuntimeError(f"Appium request failed (HTTP {response.status}).")
        try:
            decoded = json.loads(data)
            value = decoded["value"]
        except (ValueError, KeyError, TypeError):
            raise RuntimeError("Appium did not return a valid WebDriver response.") from None
        if isinstance(value, dict) and value.get("error"):
            raise RuntimeError("Appium rejected the operation.")
        return value


def parse_source(source, scale):
    if not isinstance(source, str) or len(source) > 4_000_000 or "<!" in source:
        raise RuntimeError("Appium returned invalid or oversized XML.")
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        raise RuntimeError("Appium returned invalid page source XML.") from None
    flat = []
    pending = [(root, "0", None)]
    while pending and len(flat) < 2500:
        item, identifier, parent = pending.pop()
        attr = item.attrib
        role = attr.get("type") or attr.get("class") or item.tag
        secure = "SecureTextField" in role or attr.get("password") == "true"
        node = {
            "id": identifier, "parent_id": parent, "role": role,
            "name": attr.get("label") or attr.get("content-desc") or attr.get("name") or "",
            "text": "" if secure else (attr.get("value") or attr.get("text") or ""),
            "visible": attr.get("visible", attr.get("displayed", "true")) == "true",
            "enabled": attr.get("enabled", "true") == "true",
        }
        if secure:
            node["name"] = ""
        if "resource-id" in attr:
            node["resource_id"] = attr["resource-id"]
        bounds = BOUNDS.fullmatch(attr.get("bounds", ""))
        if bounds:
            x, y, right, bottom = map(int, bounds.groups())
            width, height = right - x, bottom - y
        else:
            try:
                x, y, width, height = (float(attr.get(field, 0)) for field in ("x", "y", "width", "height"))
            except ValueError:
                x = y = width = height = 0
        if all(map(isfinite, (x, y, width, height))) and width > 0 and height > 0:
            sx, sy = scale
            node["bounds"] = {"x": round(x * sx), "y": round(y * sy),
                              "width": round(width * sx), "height": round(height * sy)}
        flat.append(node)
        pending.extend((child, f"{identifier}.{index}", identifier)
                       for index, child in reversed(list(enumerate(item))))
    return {"nodes": flat, "truncated": bool(pending)}


class WebDriverMobile:
    def __init__(self, endpoint, capabilities, mobile, target):
        self.connection = WebDriverConnection(endpoint)
        if not isinstance(capabilities, dict) or capabilities.get("platformName", "").lower() != target:
            raise ValueError("Appium capability platformName must match the action target.")
        options = {"appium:noReset": True, "appium:newCommandTimeout": 11000, **capabilities}
        device = mobile.device if target == "ios" else mobile.legacy.adb[-1]
        if options.get("appium:udid", device) != device:
            raise ValueError("Appium and the mobile helper must select the same device.")
        options["appium:udid"] = device
        self.mobile = mobile
        self.scale = (1, 1)
        self.viewport = (1, 1)
        result = self.connection.request("POST", "/session", {"capabilities": {"alwaysMatch": options}}, timeout=180)
        identifier = result.get("sessionId") if isinstance(result, dict) else None
        if not isinstance(identifier, str) or not SESSION.fullmatch(identifier):
            raise RuntimeError("Appium did not return a valid session identifier.")
        self.prefix = "/session/" + identifier

    def capabilities(self):
        extra = {"pointer.click", "pointer.drag", "pointer.scroll", "pointer.gesture", "tree.snapshot"}
        return extra | set(self.mobile.capabilities())

    def call(self, method, path, data=None, timeout=20):
        return self.connection.request(method, self.prefix + path, data, timeout)

    def capture(self):
        try:
            image = base64.b64decode(self.call("GET", "/screenshot"), validate=True)
        except (TypeError, ValueError, binascii.Error):
            raise RuntimeError("Appium did not return a valid screenshot.") from None
        if not image.startswith(PNG) or len(image) < 24:
            raise RuntimeError("Appium did not return a PNG screenshot.")
        width, height = unpack(">II", image[16:24])
        frame = self.call("GET", "/window/rect")
        self.viewport = (frame["width"], frame["height"])
        if not all(0 < value <= 16384 for value in (*self.viewport, width, height)):
            raise RuntimeError("Appium reported an invalid viewport.")
        self.scale = (width / self.viewport[0], height / self.viewport[1])
        return image

    def execute(self, command, params):
        if command == "tree.snapshot":
            return parse_source(self.call("GET", "/source"), self.scale)
        if command == "pointer.gesture":
            return self.gesture(params["tracks"])
        if command in ("pointer.click", "pointer.drag", "pointer.scroll"):
            return self.touch(command, params)
        return self.mobile.execute(command, params)

    def pointer(self, kind, points, duration):
        x, y = points[0]
        if kind == "click":
            return self.touch("pointer.click", {"x": x, "y": y})
        return self.touch("pointer.drag", {
            "x": x, "y": y, "end_x": points[-1][0], "end_y": points[-1][1],
            "duration_ms": round(duration * 1000),
        })

    def type_text(self, text):
        if "text.insert" in self.mobile.capabilities():
            return self.mobile.execute("text.insert", {"text": text})
        if not self.mobile.legacy:
            raise RuntimeError("Legacy text input is unavailable with this Appium driver.")
        return self.mobile.legacy.type_text(text)

    def point(self, x, y, duration=0):
        if not (0 <= x < self.viewport[0] * self.scale[0] and 0 <= y < self.viewport[1] * self.scale[1]):
            raise ValueError("A gesture point is outside the latest screenshot.")
        return {"type": "pointerMove", "origin": "viewport", "duration": duration,
                "x": int(x / self.scale[0]), "y": int(y / self.scale[1])}

    def send(self, tracks):
        payload = {"actions": [
            {"type": "pointer", "id": f"finger-{index}", "parameters": {"pointerType": "touch"}, "actions": actions}
            for index, actions in enumerate(tracks)
        ]}
        try:
            self.call("POST", "/actions", payload)
        except (RuntimeError, OSError):
            try:
                self.call("DELETE", "/actions", timeout=5)
            except (RuntimeError, OSError):
                pass
            raise
        return {"fingers": len(tracks)}

    def gesture(self, tracks):
        # W3C synchronizes all touch tracks by tick. Match the segment count and timing.
        timeline = [point["duration_ms"] for point in tracks[0]]
        if timeline[0] != 0 or any([point["duration_ms"] for point in track] != timeline for track in tracks):
            raise ValueError("Touch tracks must start at zero and share the same segment timings.")
        if sum(timeline) > 6000:
            raise ValueError("Limit a gesture to six seconds.")
        actions = []
        for track in tracks:
            points = [self.point(point["x"], point["y"], point["duration_ms"]) for point in track]
            actions.append([points[0], {"type": "pointerDown", "button": 0}, *points[1:],
                            {"type": "pointerUp", "button": 0}])
        return self.send(actions)

    def touch(self, command, params):
        if params.get("button", "left") != "left":
            raise ValueError("The native mobile driver supports a single touch button.")
        x, y = params["x"], params["y"]
        start = self.point(x, y)
        down, up = {"type": "pointerDown", "button": 0}, {"type": "pointerUp", "button": 0}
        if command == "pointer.click":
            actions = [start]
            for index in range(params.get("count", 1)):
                if index:
                    actions.append({"type": "pause", "duration": 80})
                actions.extend((down, {"type": "pause", "duration": params.get("hold_ms", 80)}, up))
        else:
            if command == "pointer.scroll":
                end_x = min(max(0, x - 24 * params.get("dx", 0)), int(self.viewport[0] * self.scale[0]) - 1)
                end_y = min(max(0, y - 24 * params.get("dy", 0)), int(self.viewport[1] * self.scale[1]) - 1)
            else:
                end_x, end_y = params["end_x"], params["end_y"]
            actions = [start, down, self.point(end_x, end_y, params.get("duration_ms", 350)), up]
        return self.send([actions])

    def close(self):
        try:
            self.call("DELETE", "", timeout=8)
        finally:
            self.mobile.close()
