import asyncio
from contextlib import suppress
from ipaddress import IPv4Address
from pathlib import Path
import ssl
import struct
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from bridge import ANDROID, IOS, MDNS, permitted, endpoint, tls


def ipv4(source, destination, protocol, content, flags=0):
    eth = b"\x00" * 12 + b"\x08\x00"
    header = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(content), 1, flags, 64,
                         protocol, 0, source, destination)
    return eth + header + content


def udp(source, destination):
    return struct.pack("!HHHH", source, destination, 8, 0)


class FilterTest(unittest.TestCase):
    def test_passes_scoped_native_mdns_and_tcp(self):
        self.assertTrue(permitted(ipv4(ANDROID, MDNS, 17, udp(5353, 5353)), ANDROID, IOS))
        self.assertTrue(permitted(ipv4(IOS, ANDROID, 17, udp(5353, 40000)), IOS, ANDROID))
        self.assertTrue(permitted(ipv4(IOS, ANDROID, 6, b"\0" * 20), IOS, ANDROID))

    def test_drops_routed_traffic_spoofing_fragments_and_other_multicast(self):
        internet = IPv4Address("192.0.2.99").packed
        other_multicast = IPv4Address("224.0.0.252").packed
        self.assertFalse(permitted(ipv4(IOS, internet, 6, b"\0" * 20), IOS, ANDROID))
        self.assertFalse(permitted(ipv4(ANDROID, MDNS, 17, udp(5353, 5353)), IOS, ANDROID))
        self.assertFalse(permitted(ipv4(IOS, MDNS, 17, udp(5353, 5353), 0x2000), IOS, ANDROID))
        self.assertFalse(permitted(ipv4(IOS, MDNS, 17, udp(1234, 1234)), IOS, ANDROID))
        self.assertFalse(permitted(ipv4(IOS, other_multicast, 17, udp(5353, 5353)), IOS, ANDROID))
        self.assertFalse(permitted(b"\0" * 1515, IOS, ANDROID))

    def test_limits_arp_to_the_job_pair(self):
        mac = b"abcdef"
        arp = b"\xff" * 6 + mac + b"\x08\x06\x00\x01\x08\x00\x06\x04\x00\x01"
        self.assertTrue(permitted(arp + mac + IOS + b"\x00" * 6 + ANDROID, IOS, ANDROID))
        self.assertFalse(permitted(arp + mac + IOS + b"\x00" * 6 + MDNS, IOS, ANDROID))

    def test_only_accepts_an_origin_on_the_expected_relay(self):
        self.assertEqual(endpoint("https://example-1.trycloudflare.com"), "wss://example-1.trycloudflare.com/lan")
        for unsafe in ("http://example-1.trycloudflare.com", "https://bad.example/a",
                       "https://example.trycloudflare.com:443", "https://example.trycloudflare.com/a"):
            with self.assertRaises(ValueError):
                endpoint(unsafe)


class MutualTLSTest(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def identity(directory, name):
        cert, key = directory / f"{name}.crt", directory / f"{name}.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ed25519", "-nodes", "-days", "1",
                        "-subj", "/CN=ui-mobile-lan", "-addext", "subjectAltName=DNS:ui-mobile-lan",
                        "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
        return cert, key

    async def test_expected_peer_delivers_bytes_and_untrusted_peer_does_not(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            server_cert, server_key = self.identity(directory, "server")
            client_cert, client_key = self.identity(directory, "client")
            other_cert, other_key = self.identity(directory, "other")
            received = asyncio.Event()

            async def handle(reader, writer):
                try:
                    message = await reader.readexactly(4)
                    if message == b"test":
                        received.set()
                        writer.write(b"pass")
                        await writer.drain()
                finally:
                    writer.close()
                    await writer.wait_closed()

            def args(cert, key, peer_cert):
                return SimpleNamespace(cert=cert, key=key, peer_cert=peer_cert)

            async with await asyncio.start_server(handle, "127.0.0.1", 0,
                                                  ssl=tls(args(server_cert, server_key, client_cert), True)) as server:
                port = server.sockets[0].getsockname()[1]
                for cert, key, trusted in ((other_cert, other_key, False), (client_cert, client_key, True)):
                    response = b""
                    with suppress(ConnectionError, ssl.SSLError):
                        reader, writer = await asyncio.open_connection(
                            "127.0.0.1", port, ssl=tls(args(cert, key, server_cert), False),
                            server_hostname="ui-mobile-lan")
                        try:
                            writer.write(b"test")
                            await writer.drain()
                            response = await asyncio.wait_for(reader.read(4), timeout=5)
                        finally:
                            writer.close()
                            await writer.wait_closed()
                    self.assertEqual(response, b"pass" if trusted else b"")
                    self.assertEqual(received.is_set(), trusted)


if __name__ == "__main__":
    unittest.main()
