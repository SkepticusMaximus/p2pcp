"""test_gateway — a browser-style buyer pays a float job over the WebSocket bridge.

Speaks the p2pcp wire (HELLO -> JOB -> RESULT -> RECEIPT -> ACK) as JSON frames over
a WebSocket to the gateway, which relays to a real TCP node. This both proves the
bridge relays the protocol and is the reference frame-sequence the JS client mirrors.
"""

import asyncio
import json
import os
import unittest

from p2pcp import daemon as D, worker as WK, gateway as GW

try:
    import websockets
    _HAVE_WS = True
except ImportError:
    _HAVE_WS = False

L = D.L
W = D.W


class FloatWorker(WK.DeterministicWorker):
    vclass = WK.VCLASS_FLOAT                        # money, no replay needed


def ident(tag):
    return L.Identity.from_seed(tag.ljust(32, b"\x00"))


def hello_frame(idn, alg=0):
    """Byte-for-byte the daemon's _hello_frame — the handshake a browser reproduces."""
    msg = {"type": D.HELLO_TYPE, "account": idn.account_id.hex(),
           "nonce": os.urandom(16).hex(), "alg": alg,
           "version": D.PROTOCOL_VERSION, "caps": ["compucoin"]}
    sig = idn.sign(D._canon(msg), alg)
    return D._canon({"msg": msg, "sig": sig.hex()}).decode("utf-8")


async def ws_buy_float(gw_port, target, buyer, job=b"hello", k=5):
    """A browser-shaped float purchase over the WS gateway. Returns the output."""
    uri = f"ws://127.0.0.1:{gw_port}/?target={target[0]}:{target[1]}"
    async with websockets.connect(uri) as ws:
        await ws.send(hello_frame(buyer))                       # 1. HELLO out
        worker_acct = bytes.fromhex(json.loads(await ws.recv())["msg"]["account"])
        job_mmid = L.wire_mmid(job)
        await ws.send(W.encode({"t": W.JOB, "job": job.hex(),   # 2. JOB
                                "job_mmid": job_mmid.hex(), "n_chunks": 1,
                                "k": k, "vclass": L.VCLASS_FLOAT}).decode())
        rf = json.loads(await ws.recv())                        # 3. RESULT
        assert rf["t"] == W.RESULT, rf
        output = bytes.fromhex(rf["output"])
        assert L.wire_mmid(output) == bytes.fromhex(rf["output_mmid"])
        rcpt = L.Receipt(worker_acct, buyer.account_id, k, job_mmid,
                         bytes.fromhex(rf["output_mmid"]), L.VCLASS_FLOAT,
                         os.urandom(16), 0)
        rcpt.requester_sig = buyer.sign(rcpt.signing_bytes(), 0)  # 4. RECEIPT (buyer signs)
        await ws.send(W.encode({"t": W.RECEIPT,
                                "receipt": W.receipt_to_dict(rcpt)}).decode())
        af = json.loads(await ws.recv())                        # 5. ACK (worker co-signs)
        assert af["t"] == W.RECEIPT_ACK, af
        return output


@unittest.skipUnless(_HAVE_WS, "requires the 'gateway' extra (websockets)")
class TestGateway(unittest.TestCase):
    def test_browser_style_float_buy_over_websocket(self):
        seller = D.Daemon(ident(b"gw-seller"), worker=FloatWorker())
        s_addr = seller.start()

        async def run():
            server = await websockets.serve(GW._handle, "127.0.0.1", 0)
            gw_port = server.sockets[0].getsockname()[1]
            try:
                return await ws_buy_float(gw_port, s_addr, ident(b"gw-buyer"), k=5)
            finally:
                server.close()
                await server.wait_closed()

        try:
            out = asyncio.run(run())
            self.assertTrue(out)                               # got an answer back
            self.assertEqual(seller.ledger.balance(seller.account_id), 5)  # earned k
            self.assertEqual(seller.ledger.burnable(seller.account_id), 0)  # float, no vote
        finally:
            seller.stop()

    def test_missing_target_is_rejected(self):
        async def run():
            server = await websockets.serve(GW._handle, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            try:
                with self.assertRaises(Exception):             # closed before use
                    async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
                        await ws.recv()
            finally:
                server.close()
                await server.wait_closed()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
