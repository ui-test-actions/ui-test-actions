import base64
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from agent import Client, ClientError, NoRedirect
from contract import CommandError, validate_operation
from exchange import Exchange, MAX_FILE, MAX_FILES
from transports import prepare_transport
from tunnel import Tunnel


class ExchangeTest(unittest.TestCase):
    def test_isolated_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            exchange = Exchange(Path(temp, "files"))
            text = "مرحبًا بالعالم، ١٢٣!\nMixed 🙂".encode()
            encoded = base64.b64encode(text).decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "base64": encoded})
            self.assertEqual(Path(result["path"]).read_bytes(), text)
            self.assertEqual(exchange.execute("files.read", {"name": "note.txt"})["base64"], encoded)
            self.assertEqual(exchange.execute("files.list", {})["entries"], [{"name": "note.txt", "size": len(text)}])
            with self.assertRaises(CommandError):
                exchange.execute("files.stage", {"name": "note.txt", "base64": encoded})

    def test_traversal_and_links_are_excluded(self):
        for name in ("../../secret", r"sub\secret", "folder/../secret", "/secret", "C:secret"):
            with self.assertRaises(CommandError):
                validate_operation({"command": "files.read", "params": {"name": name}}, {"files.read"})
        with tempfile.TemporaryDirectory() as temp:
            exchange = Exchange(Path(temp, "files"))
            source = Path(temp, "private.txt")
            source.write_text("private")
            os.link(source, exchange.directory / "copy.txt")
            self.assertEqual(exchange.execute("files.list", {})["entries"], [])
            with self.assertRaises(CommandError):
                exchange.execute("files.read", {"name": "copy.txt"})
            with self.assertRaises(CommandError):
                exchange.execute("files.read", {"name": "NUL.txt"})

    def test_file_exchange_recovers_capacity_when_the_app_removes_a_file(self):
        with tempfile.TemporaryDirectory() as temp:
            exchange = Exchange(Path(temp, "files"))
            for index in range(MAX_FILES):
                exchange.execute("files.stage", {"name": f"test-{index}.txt", "base64": "dGVzdA=="})
            with self.assertRaises(CommandError) as full:
                exchange.execute("files.stage", {"name": "new.txt", "base64": ""})
            self.assertEqual((full.exception.status, full.exception.code), (413, "exchange_full"))
            (exchange.directory / "test-0.txt").unlink()
            staged = exchange.execute("files.stage", {"name": "new.txt", "base64": ""})
            self.assertEqual(staged["size"], 0)
            self.assertEqual(len(exchange.execute("files.list", {})["entries"]), MAX_FILES)

    def test_app_generated_files_cannot_exceed_the_download_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            exchange = Exchange(Path(temp, "files"))
            output = exchange.directory / "export.bin"
            output.write_bytes(b"x" * (MAX_FILE + 1))
            with self.assertRaises(CommandError) as too_large:
                exchange.execute("files.read", {"name": output.name})
            self.assertEqual((too_large.exception.status, too_large.exception.code), (413, "file_too_large"))
            output.write_bytes(b"x" * MAX_FILE)
            result = exchange.execute("files.read", {"name": output.name})
            self.assertEqual(len(base64.b64decode(result["base64"])), MAX_FILE)


class TransportTest(unittest.TestCase):
    def test_named_connector_does_not_inherit_or_reference_secret_in_arguments(self):
        with patch.dict(os.environ, {
            "UI_TEST_TUNNEL_HOSTNAME": "ui.example.com", "UI_TEST_TUNNEL_TOKEN": "private",
            "TUNNEL_LOGLEVEL": "debug", "TUNNEL_TOKEN": "ignored",
        }):
            with tempfile.TemporaryDirectory() as directory:
                transport = prepare_transport(Path(directory))
                self.assertNotIn("UI_TEST_TUNNEL_TOKEN", os.environ)
                self.assertEqual(transport.kind, "cloudflare-named")
                connector = Tunnel(Path("cloudflared"), transport.bind[1], Path(directory),
                                   transport.hostname, transport.token)
                self.assertEqual(connector.token_file.read_text(encoding="utf-8"), "private")
                self.assertNotIn("private", connector.command)
                self.assertNotIn("TUNNEL_LOGLEVEL", connector.env)
                self.assertNotIn("TUNNEL_TOKEN", connector.env)
                connector.close()
                self.assertFalse(connector.token_file.exists())

    def test_connector_retries_a_failed_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            connector = Tunnel(Path("cloudflared"), 1234, Path(directory))

            def spawn(command, *, env, stdout, stderr):
                if stdout.tell() == 0 and not getattr(spawn, "failed", False):
                    spawn.failed = True
                    return Mock(poll=Mock(return_value=1))
                stdout.write(b"https://test-session.trycloudflare.com Registered tunnel connection")
                stdout.flush()
                return Mock(poll=Mock(return_value=None))

            with patch("tunnel.subprocess.Popen", side_effect=spawn) as process:
                self.assertEqual(connector.start(time.monotonic() + 3, lambda: False),
                                 "https://test-session.trycloudflare.com")
                self.assertEqual(process.call_count, 2)
            connector.close()

    def test_client_retries_busy_request_with_identical_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory, "token")
            token.write_text("a" * 64, encoding="utf-8")
            origin = "https://test-session.example.com"
            client = Client({"url": origin}, token)
            busy = HTTPError(origin, 429, "Busy", None,
                             io.BytesIO(b'{"error":{"code":"session_busy"}}'))
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = b'{"ok":true}'
            client.opener = Mock()
            client.opener.open.side_effect = [busy, response]
            request = {"command": "text.insert", "request_id": "repeat", "params": {"text": "اختبار"}}
            with patch("agent.time.sleep"):
                self.assertEqual(json.loads(client.fetch("/v2/action", request)), {"ok": True})
            first, second = client.opener.open.call_args_list
            self.assertEqual(first.args[0].data, second.args[0].data)

    def test_client_refuses_credentials_in_url_and_redirects(self):
        for url in ("http://app.example.com", "https://user:pw@app.example.com", "https://app.example.com/path"):
            with self.assertRaises(ClientError):
                Client({"url": url}, "unused")
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.example.com"))
