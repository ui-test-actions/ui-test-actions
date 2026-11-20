from http.client import HTTPConnection
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase
from unittest.mock import Mock

from dashboard import create_server


class DashboardTest(TestCase):
    def test_protects_reads_and_mutations_and_uses_the_named_session(self):
        sessions = Mock()
        sessions.sessions.return_value = [{"device": "linux", "available": True}]
        sessions.device.return_value.action.return_value = {"ok": True}
        with TemporaryDirectory() as directory, create_server(sessions, Path(directory)) as server:
            worker = Thread(target=server.serve_forever)
            worker.start()
            try:
                port = server.server_port
                origin = f"http://127.0.0.1:{port}"
                headers = {"Authorization": "Bearer " + server.dashboard.token, "Content-Type": "application/json"}

                def request(path, extra=None, body=None):
                    conn = HTTPConnection("127.0.0.1", port)
                    try:
                        conn.request("GET" if body is None else "POST", path,
                                     json.dumps(body) if body is not None else None, headers=extra or {})
                        response = conn.getresponse()
                        return response.status, json.loads(response.read())
                    finally:
                        conn.close()

                self.assertEqual(request("/api/devices")[0], 401)
                self.assertEqual(request("/api/devices", {**headers, "Host": "unexpected.test"})[0], 403)
                self.assertEqual(request("/api/devices", headers)[1]["sessions"][0]["device"], "linux")
                action = {"command": "clipboard.get", "request_id": "dashboard-fixed"}
                self.assertEqual(request("/api/device/linux/action", headers, action)[0], 403)
                self.assertEqual(request("/api/device/linux/action", {**headers, "Origin": "https://other.test"}, action)[0], 403)
                self.assertEqual(request("/api/device/linux/action", {**headers, "Origin": origin}, action)[0], 200)
                sessions.device.assert_called_once_with("linux")
                sessions.device.return_value.action.assert_called_once_with("clipboard.get", None, request_id="dashboard-fixed")
            finally:
                server.shutdown()
                worker.join()
                server.dashboard.executor.shutdown()
