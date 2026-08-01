"""p2pcp.relay — a keyless reverse-dial rendezvous so NAT'd nodes can sell.

A node behind a home router cannot accept inbound connections, so it cannot be
reached to sell compute — without help the mesh is LAN / public-IP only. This
relay is the break-out. A seller **dials out** to the relay (NAT always allows
outbound) and **parks** the connection, advertising the class it serves; a buyer
dials the relay asking for that class, and the relay **splices** the two. From
then on it shuttles opaque p2pcp frames blind, both directions, until either side
closes.

Like `gateway` and `model_worker`, the relay is a DUMB, KEYLESS pipe: it reads ONE
control frame to route (RLY_SELL / RLY_BUY), then relays frames it never
interprets. It holds no key, signs nothing, and imports no ledger / consensus /
daemon / worker — so it cannot forge a receipt or spend a coin. Trust stays
exactly where it was: end-to-end ed25519 between the real buyer and the real
seller, who trust the relay no more than the open internet between them.

It speaks through the ONE organ (`organ.SocketOrgan` + framed `Peer`), so it is an
ordinary organ-user, not a new network limb — the one-organ rule (§1.5) still
holds and `test_network_boundary` stays green with no exemption needed.

    python -m p2pcp.relay --host 0.0.0.0 --port 8700 [--secret SHARED]

`--secret` gates who may register / connect (an allow-list by shared key): the mesh
across the internet, but only for parties who hold the secret — until the open-
admission economics (cheap fresh keys → sockpuppet weight, still open; see
daemon.py's admission-control note) are settled. With no secret the relay is OPEN.
"""

import argparse
import threading

from . import organ as SOCK
from . import wire as W

CTRL_TIMEOUT = 30.0        # a registrant / caller must send its control frame promptly
ACCEPT_TICK = 0.3          # accept-loop poll cadence, so stop() stays responsive


class Relay:
    """A keyless reverse-dial rendezvous. Parks sellers by capability; splices a
    buyer to a parked seller of the class it asks for. Holds no key — every frame
    it moves is opaque, and the trade's trust is the counterparties' signatures."""

    def __init__(self, secret=None):
        self.secret = secret or None
        self.organ = SOCK.SocketOrgan()
        self._pools = {}                 # cap -> list[Peer]  (parked sellers, LIFO)
        self._lock = threading.Lock()
        self._running = False
        self._accept_thread = None
        self.registered = 0              # observability: cumulative parks
        self.spliced = 0                 # observability: cumulative buyer matches

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self, host="127.0.0.1", port=0):
        """Bind, listen, spawn the accept loop. Returns the bound (host, port)."""
        addr = self.organ.listen(host, port)
        self._running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="p2pcp-relay", daemon=True)
        self._accept_thread.start()
        return addr

    def stop(self):
        """Stop accepting, close the organ, drop every parked seller. Idempotent."""
        self._running = False
        self.organ.close()
        if self._accept_thread is not None:
            self._accept_thread.join(2.0)
            self._accept_thread = None
        with self._lock:
            for pool in self._pools.values():
                for peer in pool:
                    peer.close()
            self._pools.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()

    def parked(self, cap=None):
        """How many sellers are parked (for `cap`, or all). Observability/tests."""
        with self._lock:
            if cap is None:
                return sum(len(v) for v in self._pools.values())
            return len(self._pools.get(cap, []))

    # ── accept + route ───────────────────────────────────────────────────────
    def _accept_loop(self):
        while self._running:
            try:
                peer = self.organ.accept(timeout=ACCEPT_TICK)
            except SOCK.OrganTimeout:
                continue
            except SOCK.OrganError:
                break                    # organ closed → stop() in progress
            threading.Thread(target=self._route, args=(peer,),
                             name="p2pcp-relay-conn", daemon=True).start()

    def _route(self, peer):
        """Read ONE control frame and route. A malformed/oversized frame, or one
        without the shared secret, is dropped — the relay does nothing else with a
        stranger who won't say what it wants."""
        try:
            ctrl = W.decode(peer.recv(timeout=CTRL_TIMEOUT))
        except (SOCK.OrganError, ValueError):
            peer.close()
            return
        if self.secret is not None and ctrl.get("secret") != self.secret:
            peer.close()                 # not on the allow-list
            return
        t = ctrl.get("t")
        cap = ctrl.get("cap") or ""
        if t == W.RLY_SELL:
            self._park(cap, peer)        # held for a future buyer; do NOT close
        elif t == W.RLY_BUY:
            self._match(cap, peer)
        else:
            peer.close()

    def _park(self, cap, peer):
        with self._lock:
            self._pools.setdefault(cap, []).append(peer)
            self.registered += 1

    def _match(self, cap, buyer):
        # Hand the buyer one parked seller of this class. Parked peers may have
        # died while waiting; if this one is dead the splice ends fast and the
        # buyer settles nothing (buy_from_mesh can then try another provider).
        seller = None
        with self._lock:
            pool = self._pools.get(cap)
            if pool:
                seller = pool.pop()      # LIFO: the most-recently-parked, most-alive
        if seller is None:
            try:
                buyer.send(W.encode({"t": W.RLY_NONE}))
            except SOCK.OrganError:
                pass
            buyer.close()
            return
        with self._lock:
            self.spliced += 1
        self._splice(buyer, seller)

    # ── the splice — two frame pumps, blind ──────────────────────────────────
    def _splice(self, a, b):
        """Shuttle whole frames both ways until either side closes. Opaque: the
        relay forwards each framed message without reading it. When one pump ends
        (peer closed), closing both sockets unblocks the other pump's recv."""
        done = threading.Event()

        def pump(src, dst):
            try:
                while not done.is_set():
                    dst.send(src.recv(timeout=None))   # block: a live trade may idle
            except SOCK.OrganError:
                pass
            finally:
                done.set()

        t1 = threading.Thread(target=pump, args=(a, b), name="p2pcp-relay-ab",
                             daemon=True)
        t2 = threading.Thread(target=pump, args=(b, a), name="p2pcp-relay-ba",
                             daemon=True)
        t1.start()
        t2.start()
        done.wait()
        a.close()                        # unblocks whichever pump is still in recv
        b.close()


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="p2pcp-relay",
        description="Keyless reverse-dial rendezvous for NAT'd p2pcp nodes.")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8700)
    ap.add_argument("--secret", default=None,
                    help="shared key a registrant/caller must present (allow-list)")
    args = ap.parse_args(argv)
    relay = Relay(secret=args.secret)
    h, p = relay.start(args.host, args.port)
    gate = "  (secret required)" if args.secret else "  (OPEN — no secret)"
    print(f"[relay] reverse-dial rendezvous on {h}:{p}{gate}", flush=True)
    print("[relay] sellers park here from behind NAT; buyers reach them through it.",
          flush=True)
    print("[relay] Ctrl-C to stop.", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        relay.stop()
        print(f"\n[relay] stopped. {relay.registered} registration(s), "
              f"{relay.spliced} splice(s).", flush=True)


if __name__ == "__main__":
    main()
