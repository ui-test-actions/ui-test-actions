"""One isolated IPv4 LAN over mutually authenticated TLS carried by WebSocket."""

import argparse
import asyncio
from contextlib import suppress
from http import HTTPStatus
from ipaddress import IPv4Address
from pathlib import Path
import re
import ssl
import struct
from urllib.parse import urlsplit

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

FRAME_MAX = 1514
STREAM_CHUNK = 16384
MDNS = IPv4Address("224.0.0.251").packed
ANDROID = IPv4Address("192.168.137.10").packed
IOS = IPv4Address("192.168.137.2").packed


def permitted(frame, source, peer):
    """Keep host networking outside the bridge, including DHCP and default routes."""
    if not 14 <= len(frame) <= FRAME_MAX:
        return False
    if frame[12:14] == b"\x08\x06":
        return (len(frame) >= 42 and frame[14:22] in
                (b"\0\1\x08\0\x06\x04\0\1", b"\0\1\x08\0\x06\x04\0\2") and
                frame[22:28] == frame[6:12] and frame[28:32] == source and frame[38:42] == peer)
    if frame[12:14] != b"\x08\x00" or len(frame) < 34 or frame[14] != 0x45:
        return False
    length = int.from_bytes(frame[16:18], "big")
    if not 20 <= length <= len(frame) - 14 or int.from_bytes(frame[20:22], "big") & 0x3fff:
        return False
    if frame[26:30] != source:
        return False
    destination = frame[30:34]
    protocol = frame[23]
    if destination == peer and protocol in (1, 6):
        return True
    if protocol != 17 or length < 28 or destination not in (peer, MDNS):
        return False
    src_port, dst_port = struct.unpack("!HH", frame[34:38])
    return dst_port == 5353 or destination == peer and src_port == 5353


async def records(reader, writer, source, peer):
    while True:
        header = await reader.readexactly(2)
        length, = struct.unpack("!H", header)
        if not 14 <= length <= FRAME_MAX:
            raise ValueError("Invalid LAN frame length")
        frame = await reader.readexactly(length)
        if permitted(frame, source, peer):
            writer.write(header + frame)
            await writer.drain()


async def duplex(left, right):
    tasks = [asyncio.create_task(coroutine) for coroutine in (left, right)]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def frame_session(reader, writer, port, interface, source, peer, ready):
    process = await asyncio.create_subprocess_exec(
        str(port), interface, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
    try:
        ready.touch()
        print("Authenticated LAN peer attached", flush=True)
        await duplex(records(process.stdout, writer, source, peer),
                     records(reader, process.stdin, peer, source))
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        ready.unlink(missing_ok=True)
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
        await process.wait()
        writer.close()
        with suppress(OSError, TimeoutError):
            await writer.wait_closed()


async def websocket_proxy(websocket, reader, writer):
    async def from_socket():
        while chunk := await reader.read(STREAM_CHUNK):
            await websocket.send(chunk)

    async def from_websocket():
        async for chunk in websocket:
            if not isinstance(chunk, bytes):
                raise ValueError("Only binary transport is supported")
            writer.write(chunk)
            await writer.drain()

    try:
        await duplex(from_socket(), from_websocket())
    finally:
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()


def tls(args, server):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(args.cert, args.key)
    context.load_verify_locations(args.peer_cert)
    return context


WS_OPTIONS = {"compression": None, "max_size": STREAM_CHUNK, "max_queue": 8,
              "open_timeout": 8, "close_timeout": 2, "ping_interval": 15}


async def server(args):
    active = asyncio.Lock()

    async def peer(reader, writer):
        if active.locked():
            writer.close()
            return
        async with active:
            await frame_session(reader, writer, args.frame_port, args.interface, ANDROID, IOS, args.ready)

    async with await asyncio.start_server(peer, "127.0.0.1", 0, ssl=tls(args, True), ssl_handshake_timeout=6) as inner:
        port = inner.sockets[0].getsockname()[1]

        async def proxy(websocket):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await websocket_proxy(websocket, reader, writer)

        async def path_check(connection, request):
            if request.path != "/lan":
                return connection.respond(HTTPStatus.NOT_FOUND, "Unknown route\n")
            return None

        async with serve(proxy, "127.0.0.1", args.port, process_request=path_check, **WS_OPTIONS) as outer:
            await outer.serve_forever()


def endpoint(hostname):
    parsed = urlsplit(hostname)
    if not re.fullmatch(r"https://[a-z0-9-]+\.trycloudflare\.com", hostname):
        raise ValueError("Expected the HTTPS origin published by the paired GitHub job")
    return f"wss://{parsed.hostname}/lan"


async def client(args):
    async def proxy(reader, writer):
        try:
            async with connect(endpoint(args.origin), **WS_OPTIONS) as websocket:
                await websocket_proxy(websocket, reader, writer)
        finally:
            writer.close()

    async with await asyncio.start_server(proxy, "127.0.0.1", 0) as outer:
        port = outer.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", port, ssl=tls(args, False), server_hostname="ui-mobile-lan", ssl_handshake_timeout=12)
        await frame_session(reader, writer, args.frame_port, args.interface, IOS, ANDROID, args.ready)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("server", "client"))
    parser.add_argument("--interface", required=True)
    parser.add_argument("--frame-port", required=True, type=Path)
    parser.add_argument("--cert", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--peer-cert", required=True, type=Path)
    parser.add_argument("--ready", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--origin")
    args = parser.parse_args()
    asyncio.run(server(args) if args.role == "server" else client(args))


if __name__ == "__main__":
    main()
