from io import BytesIO
import json
from unittest import TestCase
from unittest.mock import Mock

from agent import ClientError
from mcp_server import MCP, MAX_REQUEST


class MCPTest(TestCase):
    def setUp(self):
        self.sessions = Mock()
        self.mcp = MCP(self.sessions)

    def request(self, method, params=None):
        return self.mcp.request({"jsonrpc": "2.0", "id": 7, "method": method,
                                 "params": params if params is not None else {}})

    def open(self):
        response = self.request("initialize", {"protocolVersion": "2025-11-25"})
        self.assertEqual(response["result"]["protocolVersion"], "2025-11-25")
        self.assertIsNone(self.mcp.request({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_discovers_and_routes_typed_tools(self):
        self.assertEqual(self.request("tools/list")["error"]["code"], -32002)
        self.open()
        schemas = self.request("tools/list")["result"]["tools"]
        self.assertIn("ui_action", {tool["name"] for tool in schemas})
        active = self.sessions.device.return_value
        active.action.return_value = {"ok": True, "result": {"text": "أهلًا"}}
        output = self.request("tools/call", {"name": "ui_action", "arguments": {
            "device": "android", "command": "clipboard.set", "params": {"text": "أهلًا"},
            "request_id": "fixed_ui_73"}})["result"]
        self.assertFalse(output["isError"])
        self.sessions.device.assert_called_once_with("android")
        active.action.assert_called_once_with("clipboard.set", {"text": "أهلًا"}, request_id="fixed_ui_73")

    def test_rejects_unexpected_arguments_and_sanitizes_remote_errors(self):
        self.open()
        response = self.request("tools/call", {"name": "ui_screenshot", "arguments": {
            "device": "ios", "token_file": "/unapproved"}})["result"]
        self.assertEqual(response["structuredContent"]["code"], "invalid_arguments")
        self.sessions.device.assert_not_called()
        self.sessions.device.return_value.screenshot.side_effect = ClientError("a private URL", 401)
        reply = self.request("tools/call", {"name": "ui_screenshot", "arguments": {"device": "ios"}})["result"]
        self.assertEqual(reply["structuredContent"]["http_status"], 401)
        self.assertNotIn("private URL", json.dumps(reply))

    def test_recovers_from_a_malformed_or_oversized_transport_message(self):
        capture = BytesIO()
        source = BytesIO(b"x" * (MAX_REQUEST + 4) + b"\n{wrong}\n"
                         b'{"jsonrpc":"2.0","method":"ping","id":42}\n')
        self.mcp.serve(source, capture)
        replies = [json.loads(line) for line in capture.getvalue().splitlines()]
        self.assertEqual([reply.get("error", {}).get("code") for reply in replies], [-32600, -32700, None])
        self.assertEqual(replies[-1]["id"], 42)
