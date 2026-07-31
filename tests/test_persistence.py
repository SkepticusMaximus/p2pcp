"""Regression test for the earnings-persistence fix.

Before: a node credited its in-memory ledger on each settled chunk, but `serve()`
only wrote the `.ledger` file in its finally block — so a long-running (systemd)
node never flushed, and the separate `wallet` process always read 0. The fix:
`Daemon.save_ledger()` (lock-safe) + a `ledger_rev` counter so a supervisor can
autosave whenever the chain changes. This test proves a settled trade bumps the
revision and round-trips through a saved ledger to the correct balance.
"""
import tempfile

from p2pcp import node as N
from p2pcp import daemon as D
from p2pcp import worker as WK
from p2pcp import ledger as L


def _trade(n_chunks, k):
    server = D.Daemon(N.identity_from_seed("persist-srv"),
                      worker=WK.DeterministicWorker())
    host, port = server.start("127.0.0.1", 0)
    client = D.Daemon(N.identity_from_seed("persist-cli"))
    res = client.request_job(host, port, b"job-cargo", n_chunks=n_chunks, k=k,
                             vclass=L.VCLASS_NATIVE, audit=WK.DeterministicWorker())
    return server, res


def test_ledger_rev_bumps_and_save_roundtrips():
    server, res = _trade(n_chunks=3, k=2)
    try:
        assert res["settled_chunks"] == 3
        # every settled chunk mutates the chain -> the revision counter moved
        assert server.ledger_rev() >= 3
        # save_ledger persists a snapshot the separate `wallet` path can read back
        path = tempfile.mktemp(suffix=".ledger")
        server.save_ledger(path)
        reloaded = L.Ledger.load(path)
        assert reloaded.verify()                       # integrity holds
        assert reloaded.balance(server.account_id) == 6  # 3 chunks * k=2
    finally:
        server.stop()


def test_ledger_rev_starts_at_zero():
    d = D.Daemon(N.identity_from_seed("fresh"))
    assert d.ledger_rev() == 0


if __name__ == "__main__":
    import traceback
    ok = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        try:
            t(); print(f"  [PASS] {t.__name__}"); ok += 1
        except Exception:
            print(f"  [FAIL] {t.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(tests)} persistence tests passed")
    raise SystemExit(0 if ok == len(tests) else 1)
