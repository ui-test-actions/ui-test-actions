import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent import Client, ClientError, NoRedirect
from contract import CommandError, validate_operation
from exchange import Exchange
from tunnel import Tunnel, take_named_configuration


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


class TransportTest(unittest.TestCase):
    def test_named_connector_does_not_inherit_or_reference_secret_in_arguments(self):
        with patch.dict(os.environ, {
            "UI_TEST_TUNNEL_HOSTNAME": "ui.example.com", "UI_TEST_TUNNEL_TOKEN": "private",
            "TUNNEL_LOGLEVEL": "debug", "TUNNEL_TOKEN": "ignored",
        }):
            options, port = take_named_configuration()
            self.assertNotIn("UI_TEST_TUNNEL_TOKEN", os.environ)
            with tempfile.TemporaryDirectory() as directory:
                connector = Tunnel(Path("cloudflared"), port, Path(directory), **options)
                self.assertEqual(connector.token_file.read_text(encoding="utf-8"), "private")
                self.assertNotIn("private", connector.command)
                self.assertNotIn("TUNNEL_LOGLEVEL", connector.env)
                self.assertNotIn("TUNNEL_TOKEN", connector.env)
                connector.close()
                self.assertFalse(connector.token_file.exists())

    def test_client_refuses_credentials_in_url_and_redirects(self):
        for url in ("http://app.example.com", "https://user:pw@app.example.com", "https://app.example.com/path"):
            with self.assertRaises(ClientError):
                Client({"url": url}, "unused")
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.example.com"))
