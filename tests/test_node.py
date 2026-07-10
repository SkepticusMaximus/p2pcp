"""test_node — the generic standalone node library + CLI (serve / buy / wallet /
burn / find), all on the built-in demo worker or a bring-your-own callable."""

import io
import contextlib
import os
import tempfile
import unittest

from p2pcp import node, cli, daemon as D, worker as WK

L = D.L


def _seller(tag="seller", wk=None):
    d = D.Daemon(node.identity_from_seed(tag), worker=wk or WK.DeterministicWorker())
    return d, d.start()


class TestServeAndBuy(unittest.TestCase):
    def test_buy_demo_settles_and_is_weight_bearing(self):
        seller, addr = _seller("s1")
        client = None
        try:
            client, where, res = node.buy("hello", host=addr[0], port=addr[1],
                                          chunks=2, k=3)
            self.assertEqual(res["settled_chunks"], 2)
            self.assertEqual(where, addr)
            self.assertEqual(seller.ledger.burnable(seller.account_id), 6)  # a vote
        finally:
            if client:
                client.stop()
            seller.stop()

    def test_buy_discovers_via_peers_and_falls_through(self):
        seller, addr = _seller("s2")
        client = None
        try:
            client, where, res = node.buy("x", peers=[("127.0.0.1", 1), addr],
                                          chunks=1, k=2)     # first peer is dead
            self.assertEqual(where, addr)
            self.assertEqual(res["settled_chunks"], 1)
        finally:
            if client:
                client.stop()
            seller.stop()

    def test_forged_native_work_is_not_paid(self):
        class Forger(WK.DeterministicWorker):
            def run_chunk(self, job, index):
                return b"lie"
        seller, addr = _seller("s3", wk=Forger())
        client = None
        try:
            client, _where, res = node.buy("x", host=addr[0], port=addr[1], k=2)
            self.assertEqual(res["settled_chunks"], 0)       # replay-audit caught it
            self.assertEqual(seller.ledger.balance(seller.account_id), 0)
        finally:
            if client:
                client.stop()
            seller.stop()


class TestWorkerResolution(unittest.TestCase):
    def test_demo_and_default_are_deterministic_native(self):
        for spec in (None, "demo"):
            w = node.load_worker(spec)
            self.assertIsInstance(w, WK.DeterministicWorker)
            self.assertEqual(w.vclass, WK.VCLASS_NATIVE)

    def test_bad_spec_raises(self):
        with self.assertRaises(ValueError):
            node.load_worker("no-colon-here")


class TestWalletAndBurn(unittest.TestCase):
    def test_wallet_then_burn_into_weight(self):
        key = os.path.join(tempfile.mkdtemp(), "n.key")
        idn = node.load_or_create_identity(key)
        led = L.Ledger()
        cust = node.identity_from_seed("cust")
        led.open_account(idn)
        led.open_account(cust)
        led.settle_work(idn, cust, 8)                        # earns 8 weight-bearing
        led.save(key + ".ledger")
        self.assertEqual(node.wallet(key)["balance"], 8)
        self.assertEqual(node.wallet(key)["weight"], 0.0)
        w = node.burn(key, 5)
        self.assertGreater(w["weight"], 0.0)
        self.assertEqual(w["weight_bearing"], 3)

    def test_persistent_key_is_owner_only(self):
        key = os.path.join(tempfile.mkdtemp(), "k.key")
        node.load_or_create_identity(key)
        self.assertEqual(oct(os.stat(key).st_mode)[-3:], "600")


class TestCLI(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(argv)
            except SystemExit as e:
                code = e.code or 0
        return code, out.getvalue(), err.getvalue()

    def test_buy_and_find_over_the_cli(self):
        seller, addr = _seller("cli-seller")
        try:
            code, out, err = self._run(["buy", "--port", str(addr[1]), "hello",
                                        "--chunks", "2", "--k", "2"])
            self.assertEqual(code, 0)
            self.assertIn("[0]", out)
            self.assertIn("paid 4 CompuCoin", err)
            code, out, _ = self._run(["find", "--class", "native",
                                      "--peers", f"{addr[0]}:{addr[1]}"])
            self.assertEqual(out.strip(), f"{addr[0]}:{addr[1]}")
        finally:
            seller.stop()

    def test_buy_without_target_errors(self):
        code, _out, _err = self._run(["buy", "hello"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
