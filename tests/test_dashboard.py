"""Tests for the live mesh dashboard's non-GUI core (poll + compute-rate math).
The Tk view is not unit-tested (needs a display); it's a thin skin over these."""
from p2pcp import dashboard as DB


def test_addr_parse():
    s = DB.NodeState("10.28.135.251:9000")
    assert s.host == "10.28.135.251" and s.port == 9000


def test_chunks_per_sec_from_history():
    s = DB.NodeState("127.0.0.1:9999")
    s._hist = [(0.0, 10), (4.0, 30)]          # 20 chunks over 4 s → 5.0 ch/s
    assert abs(s.chunks_per_sec() - 5.0) < 1e-6


def test_rate_zero_without_two_points():
    s = DB.NodeState("127.0.0.1:9999")
    assert s.chunks_per_sec() == 0.0


def test_poll_offline_is_graceful():
    s = DB.NodeState("127.0.0.1:2")           # nothing is listening there
    s.poll()                                  # must not raise
    assert s.online is False


def test_loadgen_start_stop():
    lg = DB.LoadGen()
    assert not lg.running()
    lg.stop()                                 # idempotent, no crash before start
    assert not lg.running()


if __name__ == "__main__":
    import traceback
    ok = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        try:
            t(); print(f"  [PASS] {t.__name__}"); ok += 1
        except Exception:
            print(f"  [FAIL] {t.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(tests)} dashboard tests passed")
    raise SystemExit(0 if ok == len(tests) else 1)
