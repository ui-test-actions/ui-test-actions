"""Runner-side connection providers. None of these configure the app's network."""

from http.client import HTTPException
from ipaddress import IPv4Address, IPv4Network
import os
import secrets
import ssl
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from agent import NoRedirect
from tunnel import ConnectorCancelled, ConnectorUnavailable, HOSTNAME, Tunnel, download_tunnel


LOOPBACK = "127.0.0.1"
PRIVATE_NETWORKS = tuple(map(IPv4Network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")))
ACCESS_DENIAL = {302, 303, 307, 308, 401, 403}


class ListenerTransport:
    """A listener that the client's machine can already reach."""

    def __init__(self, address=LOOPBACK, port=0, work=None):
        self.bind = (address, port)
        self.kind = "local" if address == LOOPBACK else "private"
        self.context = None
        self.certificate = None
        self.restrict_host = True
        if self.kind == "private":
            self.context, self.certificate = private_tls(work, address)

    def start(self, session, cancelled):
        scheme = "https" if self.context else "http"
        return f"{scheme}://{self.bind[0]}:{session.server_port}"

    def maintain(self, deadline, cancelled):
        pass

    def metadata(self):
        return {"ca_pem": self.certificate} if self.certificate else {}

    def close(self):
        pass


class CloudflareTransport:
    def __init__(self, work, hostname="", token="", port=0, access=None, fallback=False):
        self.bind = (LOOPBACK, port)
        self.context = None
        self.restrict_host = False
        self.kind = "cloudflare-named" if hostname else "cloudflare-quick"
        self.hostname = hostname
        self.token = token
        self.access = access
        self.fallback = fallback
        self.work = work
        self.connector = None
        self.probe = None

    def start(self, session, cancelled):
        try:
            try:
                binary = download_tunnel(self.work)
                self.connector = Tunnel(binary, session.server_port, self.work, self.hostname, self.token)
            except (OSError, KeyError, RuntimeError) as error:
                raise ConnectorUnavailable("The pinned Cloudflare connector could not be prepared.") from error
            self.probe = RouteProbe(session.probe_path, session.id, self.access)
            origin = self.connector.start(time.monotonic() + 110, cancelled, self.probe)
        except ConnectorUnavailable:
            if not self.fallback or cancelled():
                raise
            self.close()
            self.kind = "local"
            session.expected_host = f"{LOOPBACK}:{session.server_port}"
            print("Quick Tunnel startup failed. Using the opted-in loopback listener.", flush=True)
            origin = f"http://{session.expected_host}"
        finally:
            self.token = None
            self.access = None
        return origin

    def maintain(self, deadline, cancelled):
        if not self.connector or self.connector.process.poll() is None:
            return
        if not self.hostname:
            raise ConnectorUnavailable("The Quick Tunnel process exited. Start a fresh session.")
        if cancelled():
            return
        print("Restarting the named Cloudflare connector", flush=True)
        try:
            self.connector.start(min(time.monotonic() + 55, deadline), cancelled, self.probe)
        except (ConnectorUnavailable, ConnectorCancelled):
            if not cancelled() and time.monotonic() < deadline:
                raise

    def metadata(self):
        return {"cloudflare_access": True} if self.probe and self.probe.access else {}

    def close(self):
        if self.connector:
            self.connector.close()
            self.connector = None


class RouteProbe:
    """Prove the advertised HTTPS origin reaches this listener, even with replicas."""

    def __init__(self, path, identity, access):
        self.path = path
        self.identity = identity.encode("ascii")
        self.access = access
        self.opener = build_opener(NoRedirect(), ProxyHandler({}))

    def request(self, origin, timeout, headers):
        try:
            request = Request(origin + self.path, headers=headers)
            with self.opener.open(request, timeout=timeout) as response:
                return response.status, response.read(len(self.identity) + 1)
        except HTTPError as error:
            error.close()
            return error.code, b""
        except (URLError, OSError, HTTPException):
            return 0, b""

    def __call__(self, origin, timeout):
        headers = {"Cache-Control": "no-store"}
        if not self.access:
            return self.request(origin, timeout, headers) == (200, self.identity)
        if self.request(origin, timeout / 2, headers)[0] not in ACCESS_DENIAL:
            return False
        return self.request(origin, timeout / 2, {**headers, **self.access}) == (200, self.identity)


def private_tls(work, address):
    key = work / "transport.key"
    cert = work / "transport.crt"
    subject = "ui-" + secrets.token_hex(12)
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
             "-nodes", "-sha256", "-days", "1", "-subj", f"/CN={subject}", "-addext", f"subjectAltName=IP:{address}",
             "-addext", "basicConstraints=critical,CA:FALSE", "-addext", "extendedKeyUsage=serverAuth",
             "-keyout", str(key), "-out", str(cert)],
            check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert, key)
        return context, cert.read_text(encoding="ascii")
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Private transport requires OpenSSL and a valid session certificate.") from None
    finally:
        key.unlink(missing_ok=True)


def prepare_transport(work):
    """Consume configuration and remove credentials before any app process is launched."""
    mode = os.environ.get("UI_TEST_TRANSPORT", "auto")
    hostname = os.environ.pop("UI_TEST_TUNNEL_HOSTNAME", "").lower()
    token = os.environ.pop("UI_TEST_TUNNEL_TOKEN", "")
    access_id = os.environ.pop("UI_TEST_ACCESS_CLIENT_ID", "")
    access_secret = os.environ.pop("UI_TEST_ACCESS_CLIENT_SECRET", "")
    address = os.environ.get("UI_TEST_PRIVATE_ADDRESS", "")
    fallback = os.environ.get("UI_TEST_TRANSPORT_FALLBACK", "none")
    if mode == "auto":
        mode = "cloudflare-named" if hostname or token else "cloudflare-quick"
    if fallback not in {"none", "local"} or fallback == "local" and mode != "cloudflare-quick":
        raise ValueError("transport-fallback can be local only with cloudflare-quick.")
    if mode != "cloudflare-named" and (hostname or token or access_id or access_secret):
        raise ValueError("Cloudflare Named Tunnel and Access settings require cloudflare-named.")
    if address and mode != "private":
        raise ValueError("private-address requires the private transport.")
    if mode == "local":
        return ListenerTransport()
    if mode == "cloudflare-quick":
        return CloudflareTransport(work, fallback=fallback == "local")
    if mode not in {"cloudflare-named", "private"}:
        raise ValueError("transport must be auto, cloudflare-quick, cloudflare-named, private, or local.")

    port = int(os.environ.get("UI_TEST_ORIGIN_PORT", "8787"))
    if not 1024 <= port <= 65535:
        raise ValueError("origin-port must be between 1024 and 65535.")
    if mode == "private":
        try:
            ip = IPv4Address(address)
        except ValueError:
            raise ValueError("private-address must be a locally assigned RFC 1918 or CGNAT IPv4 address.") from None
        if not any(ip in network for network in PRIVATE_NETWORKS):
            raise ValueError("private-address must be a locally assigned RFC 1918 or CGNAT IPv4 address.")
        return ListenerTransport(address, port, work)
    if not HOSTNAME.fullmatch(hostname) or hostname.endswith(".trycloudflare.com") or not token:
        raise ValueError("Configure cloudflare-named with a dedicated DNS hostname and a connector secret.")
    if bool(access_id) != bool(access_secret) or any(
        not value.isascii() or not value.isprintable() for value in (access_id, access_secret) if value
    ):
        raise ValueError("Provide both Cloudflare Access service-token values or leave both empty.")
    access = {"CF-Access-Client-Id": access_id, "CF-Access-Client-Secret": access_secret} if access_id else None
    return CloudflareTransport(work, hostname, token, port, access)
