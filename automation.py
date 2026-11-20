"""Session-local orchestration for agent commands and observable assertions."""

from collections import OrderedDict, deque
import hashlib
import io
import json
import logging
import secrets
import subprocess
import time

from recording import Recording
from interaction_trace import InteractionTrace

from contract import BATCH_REQUEST, COMMANDS, OPERATION_REQUEST, CommandError, validate, validate_operation


LOG = logging.getLogger(__name__)
RESPONSE_LIMIT = 512 * 1024
CACHE_SIZE = 64
TREE_LIMIT = 2500


def error_result(error):
    return {"code": error.code, "message": str(error)}


class Automation:
    def __init__(self, session, driver, exchange=None):
        self.session = session
        self.driver = driver
        self.exchange = exchange
        self.recording = Recording(session)
        self.trace = InteractionTrace(session)
        self.timings = deque(maxlen=256)
        self.replies = OrderedDict()
        self.baselines = OrderedDict()
        self.snapshot = None

    def capabilities(self):
        provided = set(self.driver.capabilities()) if self.driver else set()
        provided.update(("visual.sample", "visual.wait", "recording.start", "recording.stop", "trace.start", "trace.stop",
                         "performance.observations"))
        if self.exchange:
            provided.update(("files.list", "files.stage", "files.read"))
        if "tree.snapshot" in provided:
            provided.update(("element.find", "element.assert", "element.wait"))
            if "pointer.click" in provided:
                provided.add("element.click")
        return {name: COMMANDS[name] for name in sorted(provided) if name in COMMANDS}

    def check_live(self):
        if time.monotonic() >= self.session.deadline:
            raise CommandError("session_ended", "The session has ended.", 410)

    def execute(self, request, batch=False):
        validate(request, BATCH_REQUEST if batch else OPERATION_REQUEST, "request")
        request_id = request.get("request_id")
        fingerprint = hashlib.sha256(json.dumps(
            [batch, request], sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode()).digest()
        if request_id in self.replies:
            saved_hash, status, reply = self.replies[request_id]
            if fingerprint != saved_hash:
                raise CommandError("request_conflict", "This request ID was already used for different input.", 409)
            self.replies.move_to_end(request_id)
            return status, reply

        capabilities = self.capabilities()
        operations = request["steps"] if batch else [request]
        commands = [validate_operation(item, capabilities) for item in operations]
        output = []
        batch_deadline = time.monotonic() + 30
        for name, params in commands:
            started = time.monotonic()
            count = len(output)
            try:
                self.check_live()
                if batch and time.monotonic() >= batch_deadline:
                    raise CommandError("batch_timeout", "The batch time budget has elapsed.", 408)
                result = self.dispatch(name, params)
                if name == "app.metrics":
                    result["sample_monotonic_ms"] = round(time.monotonic() * 1000, 3)
                self.trace.command(name, params, result)
                output.append({"command": name, "ok": True, "result": result})
            except CommandError as error:
                status = error.status
                self.trace.command(name, params, error=error.code)
                output.append({"command": name, "ok": False, "error": error_result(error)})
                break
            except LookupError:
                status = 404
                self.trace.command(name, params, error="target_not_found")
                output.append({"command": name, "ok": False, "error": {
                    "code": "target_not_found", "message": "The requested driver target is no longer available.",
                }})
                break
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                if isinstance(error, ValueError):
                    code, message, status = "invalid_arguments", "The driver rejected these arguments.", 400
                elif isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
                    code, message, status = "driver_timeout", "The platform command timed out.", 504
                else:
                    code, message, status = "driver_error", "The platform command failed.", 502
                LOG.warning("Command %s failed (%s)", name, type(error).__name__)
                self.trace.command(name, params, error=code)
                output.append({"command": name, "ok": False, "error": {"code": code, "message": message}})
                break
            finally:
                if name != "performance.observations" and len(output) > count:
                    self.timings.append({"command": name, "milliseconds": round((time.monotonic() - started) * 1000, 3),
                                         "ok": output[-1]["ok"]})
        else:
            status = 200
        reply = {"request_id": request_id, "ok": status == 200, "steps": output,
                 "completed": sum(step["ok"] for step in output)} if batch else {"request_id": request_id, **output[0]}
        if len(json.dumps(reply).encode()) > RESPONSE_LIMIT:
            status = 413
            reply = {"ok": False, "request_id": request_id, "error": {
                "code": "result_too_large", "message": "The driver returned more observation data than the session allows.",
            }}
        if request_id is not None:
            self.replies[request_id] = (fingerprint, status, reply)
            if len(self.replies) > CACHE_SIZE:
                self.replies.popitem(last=False)
        return status, reply

    def dispatch(self, name, params):
        if name == "tree.snapshot":
            return self.capture_tree(params.get("limit", TREE_LIMIT))
        if name == "element.click":
            return self.click_element(params)
        if name.startswith("element."):
            return self.find_element(name, params)
        if name.startswith("visual."):
            return self.visual(name, params)
        if name == "recording.start":
            return self.recording.start(params.get("duration_seconds", 10))
        if name == "recording.stop":
            return self.recording.finish()
        if name == "trace.start":
            return self.trace.start(params.get("capture_text", False))
        if name == "trace.stop":
            return self.trace.stop()
        if name == "performance.observations":
            return {"startup": self.session.startup, "actions": list(self.timings)}
        if name.startswith("files."):
            return self.exchange.execute(name, params)
        if name.startswith("pointer."):
            self.check_coordinates(params)
        if name != "clipboard.get" and name != "windows.list":
            self.snapshot = None
        return self.driver.execute(name, params)

    def check_coordinates(self, params):
        width, height = self.session.size
        for x, y in (("x", "y"), ("end_x", "end_y")):
            if x in params and not (0 <= params[x] < width and 0 <= params[y] < height):
                raise CommandError("invalid_arguments", "Coordinates must lie within the latest screen size.")

    def capture_tree(self, limit=TREE_LIMIT):
        data = self.driver.execute("tree.snapshot", {})
        if isinstance(data, list):
            data = {"nodes": data}
        if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
            raise RuntimeError("Invalid observation")
        nodes = data["nodes"][:limit]
        snapshot = {"snapshot_id": secrets.token_hex(12), "nodes": nodes,
                    "truncated": bool(data.get("truncated")) or len(data["nodes"]) > limit}
        self.snapshot = snapshot
        return snapshot

    @staticmethod
    def matches(node, selector):
        for key, value in selector.items():
            if key == "text_contains":
                if not any(value in str(node.get(field, "")) for field in ("text", "name")):
                    return False
            elif key == "properties":
                properties = node.get("properties", {})
                if any(properties.get(flag, node.get(flag)) != expected for flag, expected in value.items()):
                    return False
            elif node.get(key) != value:
                return False
        return True

    def find_element(self, name, params):
        def observe():
            snapshot = self.capture_tree()
            matches = [node for node in snapshot["nodes"] if self.matches(node, params["selector"])]
            state = params.get("state", "present")
            if state == "absent" and not matches and snapshot["truncated"]:
                raise CommandError("observation_incomplete", "The tree was truncated and cannot prove absence.", 422)
            return {"matched": len(matches), "snapshot_id": snapshot["snapshot_id"], "nodes": matches,
                    "satisfied": bool(matches) == (state == "present")}

        if name == "element.wait":
            return self.wait_for(observe, params.get("timeout_ms", 4000))
        observation = observe()
        if name == "element.assert" and not observation["satisfied"]:
            raise CommandError("assertion_failed", "The element condition was not satisfied.", 422)
        return observation

    def click_element(self, params):
        snapshot = self.snapshot
        if not snapshot or params["snapshot_id"] != snapshot["snapshot_id"]:
            raise CommandError("stale_snapshot", "Refresh the element snapshot before targeting it.", 409)
        previous = [node for node in snapshot["nodes"] if node.get("id") == params["id"]]
        if len(previous) != 1:
            raise CommandError("element_not_found", "The element ID is not unique in this snapshot.", 404)
        current = self.capture_tree()
        nodes = [node for node in current["nodes"] if node.get("id") == params["id"]]
        stable_fields = ("role", "name", "text", "resource_id", "bounds")
        if len(nodes) != 1 or any(nodes[0].get(key) != previous[0].get(key) for key in stable_fields):
            raise CommandError("stale_snapshot", "The target changed after inspection.", 409)
        node = nodes[0]
        bounds = node.get("bounds")
        if not bounds or node.get("visible") is False or node.get("enabled") is False:
            raise CommandError("element_not_actionable", "The element has no usable visible bounds.", 422)
        width, height = self.session.size
        left, top = max(0, bounds["x"]), max(0, bounds["y"])
        right, bottom = min(width, bounds["x"] + bounds["width"]), min(height, bounds["y"] + bounds["height"])
        if left >= right or top >= bottom:
            raise CommandError("element_not_actionable", "The element is outside the visible screen.", 422)
        x, y = (left + right) // 2, (top + bottom) // 2
        result = self.dispatch("pointer.click", {"x": x, "y": y})
        self.trace.click(node, current["nodes"], x, y)
        return result

    def wait_for(self, observe, timeout_ms):
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            self.check_live()
            observation = observe()
            if observation["satisfied"]:
                return observation
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CommandError("condition_timeout", "The condition was not observed before timeout.", 408)
            time.sleep(min(remaining, 0.2))

    def image(self, region):
        from PIL import Image
        self.check_live()
        with Image.open(io.BytesIO(self.session.capture())) as png:
            image = png.convert("RGB")
        if region:
            x, y = region["x"], region["y"]
            right, bottom = x + region["width"], y + region["height"]
            if right > image.width or bottom > image.height:
                raise CommandError("invalid_arguments", "The region must lie within the screen.")
            image = image.crop((x, y, right, bottom))
        return image.resize((96, 96)).tobytes()

    def visual(self, name, params):
        if name == "visual.sample":
            region = params.get("region")
            image = self.image(region)
            identifier = secrets.token_hex(12)
            self.baselines[identifier] = (region, image, self.session.size)
            if len(self.baselines) > 16:
                self.baselines.popitem(last=False)
            return {"baseline": identifier, "screen": list(self.session.size)}
        if params["baseline"] not in self.baselines:
            raise CommandError("unknown_baseline", "Capture a visual baseline in this session first.", 404)
        region, baseline, size = self.baselines[params["baseline"]]
        threshold = params.get("threshold", 3)
        condition = params.get("condition", "changed")
        stable_since = None

        def observe():
            nonlocal stable_since
            sample = self.image(region)
            if size != self.session.size:
                raise CommandError("display_changed", "Capture a new baseline after the display changed.", 409)
            difference = sum(abs(a - b) for a, b in zip(baseline, sample)) / len(baseline)
            if condition == "changed":
                satisfied = difference >= threshold
            elif difference >= threshold:
                stable_since = None
                satisfied = False
            else:
                stable_since = stable_since if stable_since is not None else time.monotonic()
                satisfied = time.monotonic() - stable_since >= 0.5
            return {"difference": round(difference, 3), "satisfied": satisfied}
        return self.wait_for(observe, params.get("timeout_ms", 4000))
