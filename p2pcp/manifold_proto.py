"""p2pcp.manifold_proto — the manifold capability's wire frames + session.

New frame `type` tags on the SAME P2PCP wire (encode/decode reused from
p2pcp.wire), routed alongside JOB/RESULT/… by the node's type dispatch. This is
how two protocols share one port with no clash: the handshake advertises
caps=["compute","manifold"], and every frame self-declares its type.

Exchange (a shares a training manifold with b, b folds it in and reports):

  a → MFOLD_OFFER  {mmid, dims, axis, confidence}
  b → MFOLD_REQ    {mmid}                    (only if b's mmid differs)
  a → MFOLD_BATCH  {packets}                 (I/O words carrying MAP words)
  b → MFOLD_RATE   {alignment, mmoe, mmid_match, new_mmid}

`ManifoldPeer` is a pure state machine (no sockets, no clock) — the node's
serve loop calls `peer.on_frame(frame)` and puts any returned frame on the
wire. `drive()` runs the whole thing in-process for tests and the demo.
"""

from . import wire
from . import manifold as M

MFOLD_OFFER = "MFOLD_OFFER"
MFOLD_REQ = "MFOLD_REQ"
MFOLD_BATCH = "MFOLD_BATCH"
MFOLD_RATE = "MFOLD_RATE"
MFOLD_TYPES = (MFOLD_OFFER, MFOLD_REQ, MFOLD_BATCH, MFOLD_RATE)


def encode(frame: dict) -> bytes:
    return wire.encode(frame)


def decode(payload: bytes) -> dict:
    return wire.decode(payload)


class ManifoldPeer:
    """One side of a manifold exchange. Holds the local manifold; folds in a
    peer's on receipt, precision-weighted. `last_rating` is b's view of a's
    contribution; `peer_rating` is what a hears back from b."""

    def __init__(self, local: M.Manifold, name="peer"):
        self.local = local
        self.name = name
        self.last_rating = None       # rating I computed on an incoming batch
        self.peer_rating = None       # rating a peer reported back to me
        self.log = []

    # producer: start an exchange by offering what I hold
    def offer(self) -> dict:
        self.log.append("offer")
        return {"type": MFOLD_OFFER, "protocol": M.PROTOCOL,
                "mmid": self.local.mmid(), "dims": sorted(self.local.dims),
                "axis": list(self.local.axis), "confidence": self.local.confidence}

    # the node's serve loop hands every MFOLD_* frame here; returns a reply or None
    def on_frame(self, frame: dict):
        t = frame.get("type")
        if t == MFOLD_OFFER:
            self.log.append("recv offer")
            if frame.get("mmid") == self.local.mmid():
                return None                       # already identical — nothing to do
            return {"type": MFOLD_REQ, "mmid": frame.get("mmid")}
        if t == MFOLD_REQ:
            self.log.append("recv req -> batch")
            return {"type": MFOLD_BATCH,
                    "packets": M.to_map_packets(self.local)}
        if t == MFOLD_BATCH:
            incoming = M.from_map_packets(frame.get("packets", []))
            r = M.rate(self.local, incoming)
            self.last_rating = r
            self.local = M.restage(self.local, incoming, r)   # fold it in
            self.log.append(f"recv batch -> restage (align={r['alignment']:.3f})")
            return {"type": MFOLD_RATE, "alignment": r["alignment"],
                    "mmoe": r["mmoe"], "mmid_match": r["mmid_match"],
                    "new_mmid": self.local.mmid()}
        if t == MFOLD_RATE:
            self.peer_rating = frame
            self.log.append(f"recv rate (peer align={frame.get('alignment'):.3f})")
            return None
        return None      # not a manifold frame — the node routes it elsewhere


def drive(a: ManifoldPeer, b: ManifoldPeer):
    """Run a full a→b manifold exchange in-process, frame by frame, exactly as
    the socket loop would — every frame is encode()'d and decode()'d across the
    hop to prove it is wire-safe. Returns whether the two ended in agreement."""
    def hop(sender_frame, receiver):
        return receiver.on_frame(decode(encode(sender_frame)))   # over the wire

    req = hop(a.offer(), b)                # OFFER -> (REQ | None if already equal)
    if req is None:
        return {"a": a, "b": b, "converged": True}
    batch = hop(req, a)                    # REQ   -> BATCH
    ratef = hop(batch, b)                  # BATCH -> RATE   (b restages here)
    if ratef is not None:
        hop(ratef, a)                     # RATE  -> None   (a records b's view)
    return {"a": a, "b": b, "converged": a.local.mmid() == b.local.mmid()}
