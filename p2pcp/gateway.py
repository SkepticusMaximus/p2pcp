"""p2pcp.gateway — a WebSocket <-> TCP bridge so browsers can join the mesh.

A browser can't open a raw TCP socket, so it speaks p2pcp's JSON frames over a
WebSocket to this gateway, which relays them to a real TCP node and back — one whole
p2pcp frame per WebSocket message.

The gateway is a DUMB frame pipe: it holds no key and signs nothing, so it cannot
forge a browser's receipts or spend its CompuCoin. It can see the (already
plaintext) frames, exactly like any relay peer — trust comes from the browser's own
ed25519 signatures, never from trusting the gateway.

Requires the `gateway` extra:  pip install 'p2pcp[gateway]'   (adds `websockets`).
Run:   python -m p2pcp.gateway --host 0.0.0.0 --port 8800
A browser connects to   ws://<gateway>:8800/?target=<node-host>:<node-port>
and exchanges whole p2pcp frames (JSON) with that node.
"""

import argparse
import asyncio
import struct
from urllib.parse import urlparse, parse_qs

from .organ import MAX_FRAME

_LEN = struct.Struct(">I")          # p2pcp's 4-byte big-endian length prefix (organ)


def _target(path):
    """Parse ?target=host:port from the WebSocket request path."""
    q = parse_qs(urlparse(path or "").query)
    tgt = (q.get("target") or [""])[0]
    host, _, port = tgt.rpartition(":")
    return (host or "127.0.0.1"), int(port)


async def _tcp_to_ws(reader, ws):
    """Read whole length-prefixed frames off the TCP node, forward each as one WS
    message. A lie in the length prefix can't make us allocate a gigabyte (§13)."""
    while True:
        header = await reader.readexactly(_LEN.size)
        (length,) = _LEN.unpack(header)
        if length > MAX_FRAME:
            await ws.close(code=1009, reason="frame exceeds MAX_FRAME")
            return
        body = await reader.readexactly(length) if length else b""
        await ws.send(body.decode("utf-8"))


async def _ws_to_tcp(ws, writer):
    """Forward each WS message (one p2pcp frame) to the TCP node, length-prefixed."""
    async for message in ws:
        payload = message.encode("utf-8") if isinstance(message, str) else message
        if len(payload) > MAX_FRAME:
            continue                                # never tunnel an oversized frame
        writer.write(_LEN.pack(len(payload)) + payload)
        await writer.drain()


async def _handle(ws, path=None):
    # websockets<11 passes the request path as the 2nd arg; >=11 exposes ws.path.
    path = path if path is not None else getattr(ws, "path", "")
    try:
        host, port = _target(path)
    except (ValueError, TypeError):
        await ws.close(code=1008, reason="bad or missing ?target=host:port")
        return
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError as e:                            # node offline / unreachable
        await ws.close(code=1011, reason=f"cannot reach {host}:{port}: {e}")
        return
    up = asyncio.ensure_future(_ws_to_tcp(ws, writer))
    down = asyncio.ensure_future(_tcp_to_ws(reader, ws))
    try:
        await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (up, down):
            t.cancel()
        writer.close()


async def serve(host="127.0.0.1", port=8800, ready=None):
    """Run the gateway until cancelled. `ready`, if given, is an asyncio.Event set
    once the server is accepting (handy for tests)."""
    import websockets
    async with websockets.serve(_handle, host, port, max_size=MAX_FRAME + 64):
        print(f"[gateway] ws://{host}:{port}/?target=<node-host>:<port>", flush=True)
        if ready is not None:
            ready.set()
        await asyncio.Future()                     # run forever


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="p2pcp-gateway",
        description="WebSocket<->TCP bridge for browser p2pcp clients.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8800)
    args = ap.parse_args(argv)
    try:
        asyncio.run(serve(args.host, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
