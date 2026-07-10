"""p2pcp — command-line client for the CompuCoin compute mesh.

  p2pcp serve  [--worker mod:fn] [--float] [--port P] [--keyfile K] [--peers ...]
      Sell compute for CompuCoin. With no --worker, runs the built-in demo worker
      (a deterministic, replay-auditable native worker). --worker mod:fn sells your
      own callable fn(job: bytes, index: int) -> bytes; add --float if it isn't
      bit-exactly reproducible.

  p2pcp buy "job" (--port P | --peers h:p,...) [--k N] [--chunks N] [--float]
      Buy compute. Native work is replay-audited before you pay (--worker mod:fn to
      audit your own class; default audits the demo worker). --peers discovers a
      provider and falls through if one is down.

  p2pcp wallet --keyfile K            show account, balance, burnable, voting weight
  p2pcp burn   --keyfile K --amount N burn earned credit into a governance vote
  p2pcp status --port P               a node's public status
  p2pcp find   --class native|float --peers h:p,...   find providers for a class

The wire is byte-identical to loopback: run `serve` on one box and `buy --host <ip>`
from another — same CLI, real network. Ctrl-C stops a server.
"""

import argparse
import sys

from . import node
from . import worker as WK


def _serve(args):
    wk = node.load_worker(args.worker, vclass="float" if args.float_ else "native")
    node.serve(wk, host=args.host, port=args.port, seed=args.seed,
               keyfile=args.keyfile, peers=node.parse_peers(args.peers),
               label=args.worker or "demo")


def _buy(args):
    if not args.peers and args.port is None:
        print("[buy] give --port (a node) or --peers (discover one)",
              file=sys.stderr)
        raise SystemExit(1)
    client, addr, res = node.buy(
        args.job, host=args.host, port=args.port,
        peers=node.parse_peers(args.peers) if args.peers else None,
        chunks=args.chunks, k=args.k,
        vclass="float" if args.float_ else "native",
        audit_worker=args.worker, seed=args.seed)
    try:
        if res is None or res.get("settled_chunks", 0) < 1:
            print("[buy] nothing settled (node offline, refused, or audit failed).",
                  file=sys.stderr)
            raise SystemExit(1)
        for i, out in enumerate(res["outputs"]):
            print(f"[{i}] {out.decode('utf-8', 'replace')}")
        where = f" via {addr[0]}:{addr[1]}" if addr else ""
        print(f"\n[buy] paid {res['paid']} CompuCoin to "
              f"{res['worker'].hex()[:16]}…{where}", file=sys.stderr)
    finally:
        client.stop()


def _wallet(args):
    w = node.wallet(args.keyfile)
    print(f"account:        {w['account']}")
    print(f"balance:        {w['balance']} CompuCoin")
    print(f"weight-bearing: {w['weight_bearing']} (burnable, replay-class)")
    print(f"voting weight:  {w['weight']:.3f} (decayed burn)")


def _burn(args):
    try:
        w = node.burn(args.keyfile, args.amount)
    except node.L.P2PCPError as e:
        print(f"[burn] refused: {e}", file=sys.stderr)
        raise SystemExit(1)
    print(f"burned {args.amount} → voting weight {w['weight']:.3f}  "
          f"(weight-bearing left: {w['weight_bearing']})")


def _status(args):
    st = node.node_status(args.host, args.port)
    if not st:
        print("[status] no response (node offline?)", file=sys.stderr)
        raise SystemExit(1)
    for key in ("account", "workers", "version", "caps", "peers", "jobs_served"):
        print(f"{key}: {st.get(key)}")


def _find(args):
    hits = node.find_providers("compute:" + args.klass, node.parse_peers(args.peers))
    if not hits:
        print(f"[find] no node advertising compute:{args.klass}", file=sys.stderr)
        raise SystemExit(1)
    for h, p in hits:
        print(f"{h}:{p}")


def build_parser():
    ap = argparse.ArgumentParser(prog="p2pcp", description="CompuCoin compute mesh.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("serve", help="sell compute for CompuCoin")
    ps.add_argument("--worker", help="mod:callable to sell (default: demo worker)")
    ps.add_argument("--float", dest="float_", action="store_true",
                    help="declare the worker float-class (not bit-reproducible)")
    ps.add_argument("--host", default="127.0.0.1")
    ps.add_argument("--port", type=int, default=0)
    ps.add_argument("--seed", default="node")
    ps.add_argument("--keyfile", help="persist identity + earnings + peer book")
    ps.add_argument("--peers", help="bootstrap peers, host:port,host:port")
    ps.set_defaults(fn=_serve)

    pb = sub.add_parser("buy", help="buy compute (replay-audited)")
    pb.add_argument("job", help="the job payload (text)")
    pb.add_argument("--host", default="127.0.0.1")
    pb.add_argument("--port", type=int, help="a specific node (else --peers)")
    pb.add_argument("--peers", help="discover a provider among these host:port,...")
    pb.add_argument("--k", type=int, default=3, help="price per chunk (CompuCoin)")
    pb.add_argument("--chunks", type=int, default=1)
    pb.add_argument("--float", dest="float_", action="store_true",
                    help="buy float-class work (no replay audit)")
    pb.add_argument("--worker", default="demo",
                    help="mod:callable to replay-audit native work (default: demo)")
    pb.add_argument("--seed", default="buyer")
    pb.set_defaults(fn=_buy)

    pw = sub.add_parser("wallet", help="show account + CompuCoin + voting weight")
    pw.add_argument("--keyfile", required=True)
    pw.set_defaults(fn=_wallet)

    pn = sub.add_parser("burn", help="burn earned credit into a governance vote")
    pn.add_argument("--keyfile", required=True)
    pn.add_argument("--amount", type=int, required=True)
    pn.set_defaults(fn=_burn)

    pt = sub.add_parser("status", help="query a node's public status")
    pt.add_argument("--host", default="127.0.0.1")
    pt.add_argument("--port", type=int, required=True)
    pt.set_defaults(fn=_status)

    pf = sub.add_parser("find", help="find nodes serving a compute class")
    pf.add_argument("--class", dest="klass", choices=["native", "float"],
                    required=True)
    pf.add_argument("--peers", required=True, help="candidates host:port,host:port")
    pf.set_defaults(fn=_find)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
