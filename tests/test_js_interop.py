"""test_js_interop — the browser JS client is byte-identical to the Python core.

Two proofs, both skipped unless Node + the web deps are installed
(`cd web && npm install`):

  1. Byte-exactness: the JS canonical encoder, SHA3 wire digest, account derivation,
     and receipt signing bytes match Python exactly — and a JS-signed receipt
     verifies under PyNaCl. (Deterministic, fixed seed.)
  2. End to end: a real Node buyer running web/p2pcp.js buys a float job through the
     Python WebSocket gateway from a Python seller, and the seller earns the coin.
"""

import asyncio
import json
import os
import shutil
import subprocess
import unittest

from p2pcp import daemon as D, worker as WK, gateway as GW

try:
    import websockets
    _HAVE_WS = True
except ImportError:
    _HAVE_WS = False

L = D.L
_HERE = os.path.dirname(os.path.abspath(__file__))
_WEB = os.path.join(os.path.dirname(_HERE), "web")
_NODE = shutil.which("node")
_HAVE_JS = bool(_NODE) and os.path.isdir(os.path.join(_WEB, "node_modules"))
_SKIP = "requires Node + web deps (cd web && npm install)"


def ident(tag):
    return L.Identity.from_seed(tag.ljust(32, b"\x00"))


@unittest.skipUnless(_HAVE_JS, _SKIP)
class TestByteExactness(unittest.TestCase):
    def setUp(self):
        out = subprocess.run([_NODE, "vectors.mjs"], cwd=_WEB, capture_output=True,
                             text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.v = json.loads(out.stdout)

    def test_account_from_seed_matches_pynacl(self):
        self.assertEqual(self.v["account"],
                         L.Identity.from_seed(bytes([1] * 32)).account_id.hex())

    def test_canonical_encoder_matches(self):
        obj = {"b": 2, "a": 1, "nested": {"y": 1, "x": 2}, "arr": [3, 1, 2]}
        self.assertEqual(self.v["canonSample"].encode(), D._canon(obj))

    def test_wire_digest_matches(self):
        self.assertEqual(self.v["sha3abc"], L.wire_mmid(b"abc").hex())

    def test_receipt_signing_bytes_and_signature(self):
        rp = self.v["receiptPayload"]
        rcpt = L.Receipt(bytes.fromhex(rp["worker"]), bytes.fromhex(rp["requester"]),
                         rp["amount"], bytes.fromhex(rp["job_commit"]),
                         bytes.fromhex(rp["output_commit"]), rp["vclass"],
                         bytes.fromhex(rp["nonce"]), rp["alg"])
        self.assertEqual(rcpt.signing_bytes(), self.v["receiptCanon"].encode())
        # a receipt SIGNED in JS verifies under PyNaCl over those exact bytes
        self.assertTrue(L.get_alg(0).verify(
            bytes.fromhex(rp["requester"]), bytes.fromhex(self.v["receiptSig"]),
            rcpt.signing_bytes()))


@unittest.skipUnless(_HAVE_JS and _HAVE_WS, _SKIP)
class TestBrowserBuysThroughGateway(unittest.TestCase):
    def test_node_buyer_settles_a_float_job(self):
        def echo(job, index):
            return b"answer: " + job

        class FloatEcho(WK.FunctionWorker):
            pass

        seller = D.Daemon(ident(b"js-seller"),
                          worker=WK.FunctionWorker(echo, vclass=WK.VCLASS_FLOAT))
        s_addr = seller.start()

        async def run():
            server = await websockets.serve(GW._handle, "127.0.0.1", 0)
            gw_port = server.sockets[0].getsockname()[1]
            try:
                proc = await asyncio.create_subprocess_exec(
                    _NODE, "e2e_buy.mjs", str(gw_port), s_addr[0], str(s_addr[1]),
                    "5", "hello", "from", "the", "browser",
                    cwd=_WEB, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
                return proc.returncode, out.decode(), err.decode()
            finally:
                server.close()
                await server.wait_closed()

        try:
            code, out, err = asyncio.run(run())
            self.assertEqual(code, 0, err)
            result = json.loads(out.strip().splitlines()[-1])
            self.assertEqual(result["output"], "answer: hello from the browser")
            self.assertEqual(result["paid"], 5)
            self.assertEqual(result["worker"], seller.account_id.hex())
            # the seller really earned the coin over the browser path
            self.assertEqual(seller.ledger.balance(seller.account_id), 5)
        finally:
            seller.stop()


if __name__ == "__main__":
    unittest.main()
