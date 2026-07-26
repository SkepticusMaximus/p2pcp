"""Tests for the Vector Manifold subsystem + its wire protocol.

Covers the captain's whole pipeline: vector-as-object (curve fit), render,
packetise as MAP words, DIF + MMID/MMOE rate, precision-weighted re-stage, and
the two-peer capability exchange over encoded/decoded frames. Pure Python,
stdlib only — runs under pytest or the bare runner at the bottom.
"""
import math

from p2pcp import manifold as M
from p2pcp import manifold_proto as P


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


# ── step 1: vector-as-object — curve fitting round-trips per kind ────────────
def test_fit_linear():
    ts = list(range(6))
    ys = [3 * t + 1 for t in ts]
    kind, coeffs = M.fit_curve(ts, ys)
    assert kind == M.LINEAR
    assert approx(M.eval_curve(kind, coeffs, 10), 31, 1e-4)


def test_fit_poly2():
    ts = [-2, -1, 0, 1, 2, 3]
    ys = [t * t - 2 * t + 1 for t in ts]
    kind, coeffs = M.fit_curve(ts, ys)
    assert kind == M.POLY2
    assert approx(M.eval_curve(kind, coeffs, 5), 16, 1e-4)     # 25-10+1


def test_fit_exp():
    ts = [0, 1, 2, 3, 4]
    ys = [2 * math.exp(0.5 * t) for t in ts]
    kind, coeffs = M.fit_curve(ts, ys)
    assert kind == M.EXP
    assert approx(M.eval_curve(kind, coeffs, 2), 2 * math.exp(1.0), 1e-4)


# ── serialize / MMID ─────────────────────────────────────────────────────────
def _manifold_a():
    return M.Manifold.fit({
        "loss":  [(i, 5.0 * math.exp(-0.3 * i)) for i in range(8)],
        "acc":   [(i, 0.1 * i + 0.2) for i in range(8)],
        "gradN": [(i, i * i * 0.01) for i in range(8)],
    }, confidence=4.0)


def test_serialize_roundtrip():
    a = _manifold_a()
    b = M.Manifold.from_dict(a.to_dict())
    assert a.mmid() == b.mmid()
    assert set(a.dims) == set(b.dims)


def test_mmid_changes_on_change():
    a = _manifold_a()
    m1 = a.mmid()
    a.dims["acc"] = [M.LINEAR, [0.2, 0.2]]      # move a dimension
    assert a.mmid() != m1


def test_map_packet_roundtrip():
    a = _manifold_a()
    packets = M.to_map_packets(a, per_packet=2)
    assert all("io_header" in p and "map_words" in p for p in packets)   # I/O + MAP
    assert packets[0]["io_header"]["mmid"] == a.mmid()
    back = M.from_map_packets(packets)
    assert back.mmid() == a.mmid()


def test_render_ascii_runs():
    art = M.render_ascii(_manifold_a())
    assert "loss" in art and "\n" in art          # a real multi-line plot w/ legend


# ── step 4: DIF + rate (MMID vs MMOE) ────────────────────────────────────────
def test_dif_and_rate_identical():
    a = _manifold_a()
    b = M.Manifold.from_dict(a.to_dict())
    r = M.rate(a, b)
    assert r["mmid_match"] is True
    assert approx(r["alignment"], 1.0)
    assert all(v["status"] == M.SAME for v in r["dif"].values())


def test_dif_detects_move_and_new():
    a = _manifold_a()
    b = M.Manifold.from_dict(a.to_dict())
    b.dims["acc"] = [M.LINEAR, [0.5, 0.2]]        # steeper acc
    b.dims["newdim"] = [M.LINEAR, [1.0, 0.0]]     # a dim a lacks
    d = M.dif(a, b)
    assert d["acc"]["status"] == M.MOVED
    assert d["newdim"]["status"] == M.NEW
    assert d["loss"]["status"] == M.SAME
    r = M.rate(a, b)
    assert r["alignment"] < 1.0 and not r["mmid_match"]


# ── step 5: re-stage (precision-weighted / Bayesian) ─────────────────────────
def test_restage_precision_weight():
    # equal-confidence merge of y=t and y=t+10 lands in the middle (~t+5)
    lo = M.Manifold({"x": [M.LINEAR, [1.0, 0.0]]}, confidence=1.0, axis=(0, 10))
    hi = M.Manifold({"x": [M.LINEAR, [1.0, 10.0]]}, confidence=1.0, axis=(0, 10))
    merged = M.restage(lo, hi)
    mid = merged.evaluate("x", 5)
    # alignment discounts a divergent peer, so it lands between local(5) and 5+10w
    assert 5.0 <= mid <= 10.0
    assert merged.confidence > lo.confidence      # evidence accumulated


def test_restage_poison_discount():
    # a wildly divergent peer earns low alignment -> low trust -> stays near local
    local = M.Manifold({"w": [M.LINEAR, [1.0, 0.0]]}, confidence=1.0, axis=(0, 10))
    poison = M.Manifold({"w": [M.LINEAR, [1.0, 1000.0]]}, confidence=1.0, axis=(0, 10))
    merged = M.restage(local, poison)
    at5 = merged.evaluate("w", 5)
    assert abs(at5 - 5.0) < abs(at5 - 1005.0)     # much closer to local than poison


def test_restage_convergence():
    # folding a peer in moves us measurably toward it
    a = _manifold_a()
    b = M.Manifold.fit({
        "loss":  [(i, 5.2 * math.exp(-0.28 * i)) for i in range(8)],
        "acc":   [(i, 0.11 * i + 0.18) for i in range(8)],
        "gradN": [(i, i * i * 0.011) for i in range(8)],
    }, confidence=4.0)
    before = M.rate(b, a)["mmoe"]
    b2 = M.restage(b, a)
    after = M.rate(b2, a)["mmoe"]
    assert after < before                          # closer to a than before


# ── the capability exchange over the wire ────────────────────────────────────
def test_protocol_exchange_folds_in():
    a = P.ManifoldPeer(_manifold_a(), "a")
    b_local = M.Manifold.fit({
        "loss":  [(i, 5.5 * math.exp(-0.25 * i)) for i in range(8)],
        "acc":   [(i, 0.12 * i + 0.15) for i in range(8)],
        "gradN": [(i, i * i * 0.012) for i in range(8)],
    }, confidence=4.0)
    b = P.ManifoldPeer(b_local, "b")
    before = M.rate(b.local, a.local)["mmoe"]
    out = P.drive(a, b)                            # OFFER->REQ->BATCH->RATE
    after = M.rate(b.local, a.local)["mmoe"]
    assert after < before                          # b folded a's manifold in
    assert b.last_rating is not None               # b rated a
    assert a.peer_rating is not None               # a heard b's rating back
    assert 0.0 < a.peer_rating["alignment"] <= 1.0


def test_protocol_identical_short_circuits():
    a = P.ManifoldPeer(_manifold_a(), "a")
    b = P.ManifoldPeer(M.Manifold.from_dict(_manifold_a().to_dict()), "b")
    out = P.drive(a, b)
    assert out["converged"] is True               # identical mmid -> no transfer
    assert b.last_rating is None                   # nothing to fold


def test_frames_are_wire_safe():
    a = P.ManifoldPeer(_manifold_a(), "a")
    for frame in (a.offer(),
                  {"type": P.MFOLD_REQ, "mmid": "deadbeef"},
                  {"type": P.MFOLD_BATCH, "packets": M.to_map_packets(a.local)}):
        assert P.decode(P.encode(frame)) == frame  # canonical round-trip


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  [PASS] {t.__name__}")
            passed += 1
        except Exception:
            print(f"  [FAIL] {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} manifold tests passed")
    raise SystemExit(0 if passed == len(tests) else 1)
