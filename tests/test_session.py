import hashlib
from http.client import HTTPConnection
import json
import secrets
import threading
import time
import unittest

from session import Session


class FakeUI:
    def __init__(self):
        self.calls = []

    def pointer(self, kind, points, duration):
        self.calls.append((kind, points, duration))

    def type_text(self, text):
        self.calls.append(("type", text))


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_hex(32)
        self.ui = FakeUI()
        digest = hashlib.sha256(self.token.encode()).hexdigest()
        self.server = Session(digest, self.ui, "linux")
        self.server.size = (640, 480)
        self.server.deadline = time.monotonic() + 90
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True,
        )
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, token=None, body=None):
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        try:
            connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_authentication_and_reconnect(self):
        for token in (None, "0" * 64):
            self.assertEqual(self.request("GET", "/v1/screenshot", token)[0], 401)
            self.assertEqual(self.request("POST", "/v1/input", token, {"action": "type", "text": "abc"})[0], 401)
        self.assertEqual(self.ui.calls, [])
        first = self.request("GET", "/v1/session", self.token)
        second = self.request("GET", "/v1/session", self.token)
        self.assertEqual(first[0], 200)
        self.assertEqual(first[1]["id"], second[1]["id"])

    def test_input_and_expiry(self):
        click = {"action": "click", "x": 320, "y": 180}
        self.assertEqual(self.request("POST", "/v1/input", self.token, click)[0], 200)
        self.assertEqual(self.ui.calls, [("click", [(320, 180)], 0.4)])
        self.assertEqual(self.request("POST", "/v1/input", self.token, dict(click, x=640))[0], 400)
        self.assertEqual(self.request("POST", "/v1/input", self.token, {"action": "type", "text": "a\nb"})[0], 400)
        self.server.deadline = time.monotonic() - 1
        self.assertEqual(self.request("POST", "/v1/input", self.token, click)[0], 410)
        self.assertEqual(self.request("GET", "/v1/session", self.token)[0], 410)
        self.assertEqual(len(self.ui.calls), 1)


if __name__ == "__main__":
    unittest.main()
