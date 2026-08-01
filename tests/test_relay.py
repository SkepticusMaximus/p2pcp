"""test_relay.py — the reverse-dial break-out (WAN/NAT).

A node behind NAT can't accept inbound, so it dials OUT to a keyless relay and
PARKS a connection; a buyer reaches it THROUGH the relay. These tests prove:
  1. the relay holds no trust logic and opens no second network surface (it uses
     the one organ), so its frame-splicing can't forge a receipt or spend a coin;
  2. a native job settles end-to-end + replay-audits through the relay, from a
     seller the buyer NEVER dials directly (the actual break-out);
  3. a buy with no provider parked fails fast instead of hanging.

Run:  python -m unittest tests.test_relay      (or:  python tests/test_relay.py)
"""

import ast
import os
import threading
import time
import unittest

from p2pcp import daemon as D
from p2pcp import node as N
from p2pcp import relay as R
from p2pcp import worker as WK


def _wait(cond, timeout=5.0, tick=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(tick)
    return cond()


class TestRelayReverseDial(unittest.TestCase):

    def test_relay_is_keyless_and_organ_only(self):
        """The relay must import no trust module (ledger/consensus/daemon/worker)
        and no network module directly — it reaches the wire only through the one
        organ. That is exactly what keeps its exemption safe: keyless (can't sign,
        can't spend) and not a second network surface."""
        path = os.path.join(os.path.dirname(R.__file__), "relay.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        trust = {"ledger", "consensus", "daemon", "worker"}
        net = {"socket", "asyncio", "ssl", "http", "urllib", "select",
               "selectors", "socketserver", "requests", "websockets"}
        bad_trust, bad_net = set(), set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.split(".")[0] in net:
                        bad_net.add(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                top = (n.module or "").split(".")[0]
                if n.level > 0 and top in trust:
                    bad_trust.add(top)
                if n.level == 0 and top in net:
                    bad_net.add(top)
        self.assertEqual(bad_trust, set(),
                         f"relay imports trust modules {sorted(bad_trust)} — it must "
                         "stay keyless")
        self.assertEqual(bad_net, set(),
                         f"relay imports the network directly {sorted(bad_net)} — it "
                         "must speak only through the one organ")

    def test_native_job_settles_through_relay(self):
        """The break-out itself: a relay, a reverse-dial SELLER never dialed
        directly, and a BUYER that knows ONLY the relay address. A native demo job
        settles end-to-end and replay-audits — a NAT'd node just sold compute."""
        relay = R.Relay()
        rh, rp = relay.start("127.0.0.1", 0)
        seller = D.Daemon(N.identity_from_seed("seller-rev"),
                          worker=WK.DeterministicWorker())
        seller.start("127.0.0.1", 0)      # a local listener the buyer will NOT use
        stop_pool = seller.serve_reverse(rh, rp, pool=2)
        try:
            self.assertTrue(_wait(lambda: relay.parked("compute:native") >= 1),
                            "seller never parked at the relay")
            client, addr, res = N.buy("hello", via_relay=(rh, rp),
                                      chunks=1, k=3, vclass="native")
            try:
                self.assertIsNotNone(res)
                self.assertEqual(res["settled_chunks"], 1)
                self.assertEqual(res["paid"], 3)
                expect = WK.DeterministicWorker().run_chunk(b"hello", 0)
                self.assertEqual(res["outputs"][0], expect)
                self.assertEqual(addr, (rh, rp))     # reached via the relay, not direct
                self.assertEqual(relay.spliced, 1)
                # the consumed park is refilled by the pool (a fresh dial-out)
                self.assertTrue(_wait(lambda: relay.parked("compute:native") >= 1),
                                "pool did not refill after the job")
            finally:
                client.stop()
        finally:
            stop_pool()
            seller.stop()
            relay.stop()

    def test_buy_via_relay_with_no_provider_does_not_hang(self):
        """No seller parked → the relay answers RLY_NONE and the buyer fails fast.
        Bounds the failure so a missing provider can't wedge a caller."""
        relay = R.Relay()
        rh, rp = relay.start("127.0.0.1", 0)
        try:
            done = {}

            def go():
                try:
                    N.buy("x", via_relay=(rh, rp), chunks=1, k=3, vclass="native")
                    done["ok"] = True
                except Exception as e:        # RLY_NONE isn't a HELLO → handshake fails
                    done["err"] = type(e).__name__

            t = threading.Thread(target=go, daemon=True)
            t.start()
            t.join(8.0)
            self.assertFalse(t.is_alive(), "buy hung with no provider parked")
            self.assertIn("err", done, "buy should fail (not settle) with no provider")
        finally:
            relay.stop()

    def test_secret_gates_registration(self):
        """A relay with a secret drops a seller that doesn't present it, so no
        provider is ever parked — the allow-list that keeps the mesh closed to
        strangers until the open-admission economics are settled."""
        relay = R.Relay(secret="open-sesame")
        rh, rp = relay.start("127.0.0.1", 0)
        seller = D.Daemon(N.identity_from_seed("seller-nosecret"),
                          worker=WK.DeterministicWorker())
        seller.start("127.0.0.1", 0)
        stop_pool = seller.serve_reverse(rh, rp, pool=1)   # no secret supplied
        try:
            time.sleep(0.5)
            self.assertEqual(relay.parked("compute:native"), 0,
                             "seller without the secret must not be parked")
        finally:
            stop_pool()
            seller.stop()
            relay.stop()


if __name__ == "__main__":
    unittest.main()
