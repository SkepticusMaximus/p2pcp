"""p2pcp.watch — a live view of the CompuCoin mesh. Make it rain. 🪙

    python3 -m p2pcp.watch 10.28.135.251:9000 [host:port ...]

Polls each node's public STATUS every couple of seconds and redraws a table in
place: jobs, chunks, and CompuCoin balance — read straight off the wire (no
keyfile, no SSH), so you can watch ANY node on the mesh. A `+N` flashes next to a
balance the instant it climbs. Ctrl-C to stop.
"""
import sys
import time

from . import node as N

POLL_SECS = 2.0
CLEAR = "\033[2J\033[H"


def poll(addr):
    host, _, port = addr.rpartition(":")
    try:
        return N.node_status(host or "127.0.0.1", int(port)) or {"error": "no status"}
    except Exception as e:                       # a down/unreachable node isn't fatal
        return {"error": type(e).__name__}


def main(argv=None):
    addrs = list(argv if argv is not None else sys.argv[1:]) or ["127.0.0.1:9000"]
    prev = {}
    try:
        while True:
            lines = [f"  ⚫🟢  CompuCoin mesh — make it rain 🪙   {time.strftime('%H:%M:%S')}",
                     "  " + "-" * 68,
                     f"  {'node':22} {'acct':11} {'jobs':>5} {'chunks':>7} {'CompuCoin':>11}"]
            total = 0
            for a in addrs:
                st = poll(a)
                if "error" in st:
                    lines.append(f"  {a:22} {'· ' + st['error']:<11} {'—':>5} {'—':>7} {'—':>11}")
                    continue
                bal = st.get("balance", 0)
                jobs = st.get("jobs_served", 0)
                chunks = st.get("chunks_served", 0)
                acct = st.get("account", "")[:10]
                flash = ""
                if a in prev and isinstance(bal, int) and bal > prev[a]:
                    flash = f"  +{bal - prev[a]}"
                if isinstance(bal, int):
                    prev[a] = bal
                    total += bal
                lines.append(f"  {a:22} {acct:11} {jobs!s:>5} {chunks!s:>7} {bal!s:>11}{flash}")
            lines.append("  " + "-" * 68)
            lines.append(f"  {'mesh total':22} {'':11} {'':>5} {'':>7} {total!s:>11} CompuCoin")
            sys.stdout.write(CLEAR + "\n".join(lines) + "\n")
            sys.stdout.flush()
            time.sleep(POLL_SECS)
    except KeyboardInterrupt:
        print("\n  (watch stopped)")


if __name__ == "__main__":
    main()
