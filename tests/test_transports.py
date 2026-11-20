import hashlib
from http.client import HTTPConnection
from contextlib import closing
import io
import os
from pathlib import Path
import shutil
import ssl
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from agent import Client, ClientError
from session import Session
from transports import ListenerTransport, RouteProbe, prepare_transport, private_tls
from tunnel import ConnectorUnavailable


class TransportTests(unittest.TestCase):
    def configure(self, work, **settings):
        with patch.dict(os.environ, {"UI_TEST_" + key: value for key, value in settings.items()}, clear=True):
            return prepare_transport(work)

    def test_default_and_legacy_mode(self):
        self.assertEqual(self.configure(None).kind, "cloudflare-quick")
        transport = self.configure(None, TUNNEL_HOSTNAME="CI.EXAMPLE.COM", TUNNEL_TOKEN="token")
        self.assertEqual((transport.kind, transport.hostname, transport.bind), (
            "cloudflare-named", "ci.example.com", ("127.0.0.1", 8787),
        ))
        self.assertEqual(self.configure(None, TRANSPORT="local").bind, ("127.0.0.1", 0))

    def test_config_rejects_accidental_exposure_and_partial_credentials(self):
        for settings in (
            {"TRANSPORT": "private", "PRIVATE_ADDRESS": "0.0.0.0"},
            {"TRANSPORT": "private", "PRIVATE_ADDRESS": "127.0.0.1"},
            {"TRANSPORT": "private", "PRIVATE_ADDRESS": "8.8.8.8"},
            {"TRANSPORT": "private", "PRIVATE_ADDRESS": "192.168.0.8", "TRANSPORT_FALLBACK": "local"},
            {"TRANSPORT": "cloudflare-named", "TUNNEL_HOSTNAME": "ci.example.com"},
            {"TUNNEL_HOSTNAME": "ci.example.com", "TUNNEL_TOKEN": "secret", "ACCESS_CLIENT_ID": "x"},
            {"TUNNEL_HOSTNAME": "ci.trycloudflare.com", "TUNNEL_TOKEN": "secret"},
            {"TRANSPORT": "cloudflare-quick", "TUNNEL_TOKEN": "secret"},
            {"TRANSPORT": "local", "PRIVATE_ADDRESS": "10.0.0.7"},
        ):
            with self.subTest(settings=list(settings)), self.assertRaises(ValueError):
                self.configure(None, **settings)

    def test_access_probe_proves_origin_and_checks_edge_denial(self):
        origin = "https://ci.example.com"
        probe = RouteProbe("/_ui_origin/random", "right-runner", {"CF-Access-Client-Secret": "example"})
        with patch.object(probe, "request", side_effect=[(403, b""), (200, b"right-runner")]) as request:
            self.assertTrue(probe(origin, 4))
            self.assertNotIn("CF-Access-Client-Secret", request.call_args_list[0].args[2])
            self.assertIn("CF-Access-Client-Secret", request.call_args_list[1].args[2])
        for responses in ([(200, b"right-runner")], [(403, b""), (200, b"other-runner")]):
            with patch.object(probe, "request", side_effect=responses):
                self.assertFalse(probe(origin, 4))

    def test_fallback_is_opt_in_and_only_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Mock(server_port=9000, probe_path="/ready", id="fixture")
            connector = Mock()
            connector.start.side_effect = ConnectorUnavailable()
            with patch("transports.download_tunnel"), patch("transports.Tunnel", return_value=connector):
                fallback = self.configure(Path(directory), TRANSPORT_FALLBACK="local")
                self.assertEqual(fallback.start(session, lambda: False), "http://127.0.0.1:9000")
                self.assertEqual(fallback.kind, "local")
                connector.close.assert_called_once()
                default = self.configure(Path(directory))
                with self.assertRaises(ConnectorUnavailable):
                    default.start(session, lambda: False)
                connector.process.poll.return_value = 1
                with self.assertRaises(ConnectorUnavailable):
                    default.maintain(time.monotonic() + 15, lambda: False)

    def test_named_reconnect_keeps_origin_and_credentials_out_of_app_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "UI_TEST_TUNNEL_HOSTNAME": "ci.example.com", "UI_TEST_TUNNEL_TOKEN": "connector",
            "UI_TEST_ACCESS_CLIENT_ID": "edge-id", "UI_TEST_ACCESS_CLIENT_SECRET": "edge-secret",
        }):
            provider = prepare_transport(Path(directory))
            for key in ("UI_TEST_TUNNEL_TOKEN", "UI_TEST_ACCESS_CLIENT_ID", "UI_TEST_ACCESS_CLIENT_SECRET"):
                self.assertNotIn(key, os.environ)
            connector = Mock()
            connector.start.return_value = "https://ci.example.com"
            with patch("transports.download_tunnel"), patch("transports.Tunnel", return_value=connector):
                self.assertEqual(provider.start(Mock(server_port=8787, probe_path="/ready", id="fixture"), lambda: False),
                                 "https://ci.example.com")
                connector.process.poll.return_value = 1
                provider.maintain(time.monotonic() + 15, lambda: False)
                self.assertEqual(connector.start.call_count, 2)
                self.assertIs(connector.start.call_args.args[2], provider.probe)
                self.assertIsNone(provider.token)
                self.assertEqual(provider.metadata(), {"cloudflare_access": True})


class ClientTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        self.token = "a" * 64
        self.token_file = self.work / "token"
        self.token_file.write_text(self.token, encoding="ascii")

    def listener(self, transport):
        session = Session(hashlib.sha256(self.token.encode()).hexdigest(), None, "linux", transport=transport)
        session.deadline = time.monotonic() + 10
        thread = threading.Thread(target=session.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(session.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(session.shutdown)
        return session

    def test_loopback_skips_proxies_and_rejects_bad_host_and_stale_id(self):
        session = self.listener(ListenerTransport())
        config = {"url": f"http://127.0.0.1:{session.server_port}", "transport": "local", "session_id": session.id}
        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "no_proxy": ""}):
            self.assertEqual(Client(config, self.token_file).identify()["id"], session.id)
        wrong = Client({**config, "session_id": "different"}, self.token_file)
        with self.assertRaises(ClientError) as wrong_session:
            wrong.command("example", {})
        self.assertEqual(wrong_session.exception.payload["error"]["code"], "session_mismatch")
        connection = HTTPConnection("127.0.0.1", session.server_port, timeout=2)
        with closing(connection):
            connection.request("GET", "/", headers={"Host": "other.example.com"})
            self.assertEqual(connection.getresponse().status, 421)

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is needed to generate a private endpoint certificate")
    def test_private_client_verifies_artifact_certificate_and_ip_san(self):
        context, certificate = private_tls(self.work, "127.0.0.1")
        self.assertFalse((self.work / "transport.key").exists())
        transport = ListenerTransport()
        transport.context = context
        session = self.listener(transport)
        config = {"url": f"https://127.0.0.1:{session.server_port}", "transport": "private", "ca_pem": certificate}
        self.assertEqual(Client(config, self.token_file).identify()["id"], session.id)
        _, unrelated = private_tls(self.work, "127.0.0.1")
        with self.assertRaises(ClientError):
            Client({**config, "ca_pem": unrelated}, self.token_file).fetch("/v1/session", retries=0)
        with self.assertRaises(ssl.SSLCertVerificationError):
            import socket
            trusted = ssl.create_default_context(cadata=certificate)
            with socket.create_connection(("127.0.0.1", session.server_port)) as connection:
                trusted.wrap_socket(connection, server_hostname="127.0.0.2")

    def test_action_network_failure_stays_ambiguous_without_a_retry(self):
        origin = "https://ci.example.com"
        for failure in (URLError("lost"), HTTPError(origin, 504, "timeout", None, io.BytesIO(b""))):
            with self.subTest(failure=type(failure).__name__):
                client = Client({"url": origin}, self.token_file)
                client.opener = Mock()
                client.opener.open.side_effect = failure
                with self.assertRaises(ClientError) as uncertain:
                    client.command("mouse.click", {})
                self.assertEqual(uncertain.exception.payload["error"]["code"], "action_outcome_unknown")
                client.opener.open.assert_called_once()
        for url in ("http://127.0.0.2:10", "http://localhost:10", "https://127.0.0.1:10",
                    "http://127.0.0.1:10@other.example.com"):
            with self.assertRaises(ClientError):
                Client({"transport": "local", "url": url}, self.token_file)

    def test_client_never_attaches_credentials_to_another_origin(self):
        client = Client({"url": "https://ci.example.com"}, self.token_file)
        client.opener = Mock()
        for path in ("@wrong.example.com", "//wrong.example.com", "/\\wrong.example.com", "/\nwrong"):
            with self.assertRaises(ClientError):
                client.fetch(path)
        client.opener.open.assert_not_called()
