import hashlib
from http.client import HTTPConnection
import io
import json
import socket
import threading
import time
import unittest

from session import Session


class Driver:
    def __init__(self):
        self.text = ""
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.x = 1

    def capabilities(self):
        return ["text.insert", "pointer.click", "tree.snapshot"]

    def execute(self, command, params):
        if command == "tree.snapshot":
            return {"nodes": [{"id": "edit", "name": "Edit", "role": "text", "text": self.text,
                               "visible": True, "enabled": True,
                               "bounds": {"x": self.x, "y": 2, "width": 20, "height": 15}}]}
        if command == "text.insert":
            self.started.set()
            self.release.wait(2)
            self.text = params["text"]
        self.calls.append((command, params))
        return {"applied": True}

    def capture(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (64, 48), (100 if self.text else 0, 0, 0)).save(buffer, "PNG")
        return buffer.getvalue()


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.token = "b" * 64
        digest = hashlib.sha256(self.token.encode()).hexdigest()
        self.driver = Driver()
        self.server = Session(digest, self.driver, "fake", self.driver)
        self.server.size = (64, 48)
        self.server.deadline = time.monotonic() + 60
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .02})
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.driver.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, params=None, authenticated=True, mime="application/json", raw=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.token
        try:
            if params is None and raw is None:
                conn.request("GET", path, headers=headers)
            else:
                headers["Content-Type"] = mime
                conn.request("POST", path, raw if raw is not None else json.dumps(params), headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def action(self, command, params, request_id=None):
        data = {"command": command, "params": params}
        if request_id:
            data["request_id"] = request_id
        return self.request("/v2/action", data)

    def test_unicode_replay_and_batch(self):
        message = "مَرْحَبًا بالعالم، ١٢٣؟\u200f mixed English 👩🏽‍💻\n第二行"
        status, first = self.action("text.insert", {"text": message}, "same-id")
        self.assertEqual(status, 200)
        self.assertEqual(self.driver.text, message)
        self.assertEqual(self.action("text.insert", {"text": message}, "same-id"), (status, first))
        self.assertEqual(self.action("text.insert", {"text": "different"}, "same-id")[0], 409)
        self.assertEqual(len(self.driver.calls), 1)
        status, result = self.request("/v2/batch", {"steps": [
            {"command": "element.assert", "params": {"selector": {"text": message}, "state": "present"}},
            {"command": "element.assert", "params": {"selector": {"name": "missing"}, "state": "present"}},
            {"command": "text.insert", "params": {"text": "must not execute"}},
        ]})
        self.assertEqual(status, 422)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["steps"][1]["error"]["code"], "assertion_failed")
        self.assertEqual(self.driver.text, message)

    def test_invalid_batch_preflight_does_not_apply_valid_prefix(self):
        status, result = self.request("/v2/batch", {"steps": [
            {"command": "text.insert", "params": {"text": "must not execute"}},
            {"command": "pointer.click", "params": {"x": -1, "y": 0}},
        ]})
        self.assertEqual((status, result["error"]["code"]), (400, "invalid_arguments"))
        self.assertEqual(self.driver.calls, [])

    def test_replay_cache_is_bounded_and_refreshes_an_observed_id(self):
        old = {"text": "old"}
        keep = {"text": "keep"}
        self.action("text.insert", old, "old")
        cached = self.action("text.insert", keep, "keep")
        for index in range(62):
            self.action("text.insert", {"text": str(index)}, f"filler-{index}")
        self.assertEqual(self.action("text.insert", keep, "keep"), cached)
        self.assertEqual(len(self.driver.calls), 64)
        self.action("text.insert", {"text": "new"}, "new")
        self.assertEqual(self.action("text.insert", keep, "keep"), cached)
        self.action("text.insert", old, "old")
        self.assertEqual(len(self.server.automation.replies), 64)
        self.assertEqual(self.driver.calls[-1], ("text.insert", old))
        self.assertEqual(len(self.driver.calls), 66)

    def test_invalid_requests_and_discovery(self):
        self.assertEqual(self.request("/v2/capabilities", authenticated=False)[0], 401)
        capabilities = self.request("/v2/capabilities")[1]["commands"]
        self.assertIn("element.click", capabilities)
        self.assertNotIn("app.uninstall", capabilities)
        self.assertEqual(self.action("app.uninstall", {"id": "example"})[0], 422)
        for text in ("\ud800", "null\x00character"):
            self.assertEqual(self.action("text.insert", {"text": text})[0], 400)
        for x in (-1, 64, True, "1"):
            self.assertEqual(self.action("pointer.click", {"x": x, "y": 0})[0], 400)
        self.assertEqual(self.request("/v2/action", raw=b"\xff")[1]["error"]["code"], "invalid_json")
        self.assertEqual(self.request("/v2/action", raw=b"x" * 65537)[0], 413)
        self.assertEqual(self.request("/v2/action", raw=b"{}", mime="text/plain")[0], 415)
        self.assertEqual(self.driver.calls, [])

    def test_snapshot_movement_and_expiry(self):
        _, result = self.action("tree.snapshot", {})
        snapshot = result["result"]["snapshot_id"]
        self.driver.x = 2
        self.assertEqual(self.action("element.click", {"id": "edit", "snapshot_id": snapshot})[0], 409)
        _, result = self.action("element.find", {"selector": {"name": "Edit"}})
        snapshot = result["result"]["snapshot_id"]
        self.assertEqual(self.action("element.click", {"id": "edit", "snapshot_id": snapshot})[0], 200)
        self.assertEqual(self.driver.calls, [("pointer.click", {"x": 12, "y": 9})])
        self.server.deadline = time.monotonic() - 1
        self.assertEqual(self.action("tree.snapshot", {})[0], 410)

    def test_concurrent_duplicate_is_retryable(self):
        results = []
        self.driver.release.clear()
        client = threading.Thread(target=lambda: results.append(self.action("text.insert", {"text": "A"}, "busy")))
        client.start()
        self.assertTrue(self.driver.started.wait(2))
        status, result = self.action("text.insert", {"text": "A"}, "busy")
        self.assertEqual((status, result["error"]["code"]), (429, "session_busy"))
        self.driver.release.set()
        client.join(3)
        self.assertEqual(self.action("text.insert", {"text": "A"}, "busy"), results[0])
        self.assertEqual(len(self.driver.calls), 1)

    def test_disconnected_client_can_replay_an_applied_mutation(self):
        request = {"command": "text.insert", "params": {"text": "انقطع الاتصال"}, "request_id": "disconnect"}
        pending = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        self.driver.release.clear()
        pending.request("POST", "/v2/action", json.dumps(request), {
            "Authorization": "Bearer " + self.token, "Content-Type": "application/json",
        })
        self.assertTrue(self.driver.started.wait(2))
        pending.sock.shutdown(socket.SHUT_RDWR)
        pending.close()
        self.driver.release.set()
        deadline = time.monotonic() + 3
        while True:
            status, reply = self.request("/v2/action", request)
            if status != 429 or time.monotonic() >= deadline:
                break
            time.sleep(.05)
        self.assertEqual(status, 200)
        self.assertTrue(reply["ok"])
        self.assertEqual(self.driver.calls, [("text.insert", {"text": "انقطع الاتصال"})])

    def test_visual_recording_contains_observed_frames(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is installed on session runners")
        self.assertEqual(self.action("recording.start", {"duration_seconds": 2})[0], 200)
        time.sleep(.6)
        self.assertEqual(self.action("text.insert", {"text": "change"})[0], 200)
        time.sleep(.65)
        status, result = self.action("recording.stop", {})
        self.assertEqual(status, 200)
        self.assertGreaterEqual(result["result"]["frames"], 2)
        with Image.open(io.BytesIO(self.server.automation.recording.latest)) as image:
            self.assertGreaterEqual(image.n_frames, 2)

    def test_visual_observation(self):
        try:
            import PIL
        except ImportError:
            self.skipTest("Pillow is installed on session runners")
        _, result = self.action("visual.sample", {})
        sample = result["result"]["baseline"]
        self.assertEqual(self.action("visual.wait", {"baseline": sample, "timeout_ms": 100})[0], 408)
        self.action("text.insert", {"text": "change"})
        status, result = self.action("visual.wait", {"baseline": sample})
        self.assertEqual(status, 200)
        self.assertGreater(result["result"]["difference"], 30)


if __name__ == "__main__":
    unittest.main()
