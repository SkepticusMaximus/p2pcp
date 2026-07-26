"""p2pcp.manifold_demo — watch two trainers share a manifold and converge.

    python3 -m p2pcp.manifold_demo

Two peers hold slightly different training manifolds (loss / accuracy / grad-norm
curves). We render both (PIGART stand-in), then run the capability exchange over
the wire — offer → request → batch of MAP-word packets → rate → precision-weighted
re-stage — and watch the mismatch-of-expectation (MMOE) fall as they agree.
No sockets, no network: the frames are encoded and decoded across each hop, so
this is the real protocol, just in one process.
"""
import math

from . import manifold as M
from . import manifold_proto as P


def _peer(name, k):
    """A trainer whose curves wobble by factor k from a shared shape."""
    return P.ManifoldPeer(M.Manifold.fit({
        "loss":  [(i, 5.0 * k * math.exp(-0.30 / k * i)) for i in range(8)],
        "acc":   [(i, 0.10 * k * i + 0.2) for i in range(8)],
        "gradN": [(i, i * i * 0.010 * k) for i in range(8)],
    }, confidence=4.0), name)


def main():
    a, b = _peer("A", 1.00), _peer("B", 1.15)

    print("=" * 64)
    print("P2PCP VECTOR MANIFOLD — two trainers sharing weights over one wire")
    print("=" * 64)
    print("\nTrainer A — loss/acc/grad manifold:\n")
    print(M.render_ascii(a.local))
    print("\nTrainer B — same dims, a different run:\n")
    print(M.render_ascii(b.local))

    print("\n" + "-" * 64)
    print(f"A mmid: {a.local.mmid()[:16]}…")
    print(f"B mmid: {b.local.mmid()[:16]}…   (differ → there is something to share)")
    print(f"initial MMOE (B's mismatch vs A): {M.rate(b.local, a.local)['mmoe']:.4f}")

    print("\nRun 1 — A offers its manifold; B folds it in:")
    P.drive(a, b)
    print("  " + "  |  ".join(b.log[-3:]))
    print(f"  B's new confidence: {b.local.confidence:.1f} (evidence accumulated)")
    print(f"  MMOE after run 1:   {M.rate(b.local, a.local)['mmoe']:.4f}")

    # a few more rounds, alternating who offers — watch them converge
    for r in range(2, 5):
        if r % 2 == 0:
            P.drive(b, a)        # B offers, A folds in
        else:
            P.drive(a, b)        # A offers, B folds in
        mmoe = M.rate(b.local, a.local)["mmoe"]
        print(f"  MMOE after run {r}:   {mmoe:.4f}")

    print("\nConverged manifold (B, after sharing):\n")
    print(M.render_ascii(b.local))
    print("\nThat exchange rode the SAME wire as the compute protocol, routed by")
    print("frame type (MFOLD_*), advertised as caps=['compute','manifold'] — one")
    print("port, two protocols, no clash. The payload is MAP-word packets.")


if __name__ == "__main__":
    main()
