"""p2pcp.dashboard — a live Tk window on the CompuCoin mesh.

    python -m p2pcp.dashboard 10.28.135.251:9000 [host:port ...]

For every node it shows the wallet (CompuCoin, flashing green/red as it moves),
jobs + chunks served, and a COMPUTE METER — a bar of chunks/sec, i.e. how much
work that node is actually delivering into the mesh right now. The "Draw load"
toggle turns your machine into a buyer that hammers a chosen node, so you watch
its meter climb and the coins flow, in or out. Speaks the standalone p2pcp wire
over the network (STATUS carries balance/jobs/chunks), so it needs no keyfile.

Run it from the p2pcp venv (needs tkinter → system python3-tk):
    ~/.venvs/p2pcp/bin/python -m p2pcp.dashboard 10.28.135.251:9000
"""
import sys
import threading
import time

from . import node as N

POLL_MS = 1000            # status poll cadence
RATE_WINDOW = 8.0         # seconds of history the chunks/sec average spans
METER_FULL = 8.0          # chunks/sec that fills the compute bar


class NodeState:
    """Polls one node's public STATUS and derives coin-flow + compute rate."""

    def __init__(self, addr):
        self.addr = addr
        host, _, port = addr.rpartition(":")
        self.host, self.port = (host or "127.0.0.1"), int(port or 9000)
        self.online = False
        self.account = ""
        self.balance = 0
        self.jobs = 0
        self.chunks = 0
        self.coin_delta = 0
        self._hist = []       # [(monotonic_t, chunks), ...] for the rate

    def poll(self):
        try:
            s = N.node_status(self.host, self.port)
        except Exception:
            s = None
        if not s:
            self.online = False
            return
        self.online = True
        prev = self.balance
        self.balance = int(s.get("balance", 0))
        self.coin_delta = self.balance - prev
        self.jobs = int(s.get("jobs_served", 0))
        self.chunks = int(s.get("chunks_served", 0))
        self.account = (s.get("account", "") or "")[:10]
        now = time.monotonic()
        self._hist.append((now, self.chunks))
        self._hist = [(t, c) for (t, c) in self._hist if now - t <= RATE_WINDOW]

    def chunks_per_sec(self):
        if len(self._hist) < 2:
            return 0.0
        (t0, c0), (t1, c1) = self._hist[0], self._hist[-1]
        dt = t1 - t0
        return (c1 - c0) / dt if dt > 0 else 0.0


class LoadGen:
    """A background buyer: hammer a node with small native jobs to make load +
    coin flow. Replay-audited against the demo worker, so it only pays for real
    delivered work (same trade the CLI does)."""

    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self.target = None
        self.buys = 0

    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, host, port):
        self.stop()
        self.target = (host, int(port))
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread = None

    def _run(self):
        host, port = self.target
        while not self._stop.is_set():
            try:
                N.buy(f"dashboard-load-{self.buys}", host=host, port=port,
                      chunks=2, k=2)
                self.buys += 1
            except Exception:
                self._stop.wait(0.5)          # a blip: back off, don't spin
            self._stop.wait(0.3)              # gentle pacing


def main(argv=None):
    import tkinter as tk
    addrs = list(argv if argv is not None else sys.argv[1:]) or ["127.0.0.1:9000"]
    states = [NodeState(a) for a in addrs]
    load = LoadGen()

    BG, PANEL = "#12141c", "#1b1e28"
    FG, DIM = "#e8e8e8", "#8a90a0"
    GRN, RED, ACC = "#3fd08f", "#e06a6a", "#2d6a4f"
    mono = ("Monospace", 11)

    root = tk.Tk()
    root.title("P2PCP — CompuCoin mesh monitor")
    root.geometry("860x620")
    root.minsize(600, 420)
    root.configure(bg=BG)

    tk.Label(root, text="⚫🟢  CompuCoin mesh — live", bg=BG, fg=FG,
             font=("Monospace", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 2))

    cards = []
    for st in states:
        f = tk.Frame(root, bg=PANEL, bd=1, relief="solid")
        f.pack(fill="x", padx=12, pady=4)
        head = tk.Label(f, text=st.addr, bg=PANEL, fg=DIM, font=mono, anchor="w")
        head.pack(fill="x", padx=8, pady=(6, 0))
        bal = tk.Label(f, text="0 CompuCoin", bg=PANEL, fg=FG,
                       font=("Monospace", 20, "bold"), anchor="w")
        bal.pack(fill="x", padx=8)
        sub = tk.Label(f, text="", bg=PANEL, fg=DIM, font=mono, anchor="w")
        sub.pack(fill="x", padx=8)
        mrow = tk.Frame(f, bg=PANEL)
        mrow.pack(fill="x", padx=8, pady=(2, 8))
        tk.Label(mrow, text="compute", bg=PANEL, fg=DIM,
                 font=("Monospace", 9)).pack(side="left")
        cv = tk.Canvas(mrow, height=14, bg="#0c0e14", highlightthickness=0)
        cv.pack(side="left", fill="x", expand=True, padx=6)
        rate = tk.Label(mrow, text="0.0 ch/s", bg=PANEL, fg=FG,
                        font=("Monospace", 9), width=11, anchor="e")
        rate.pack(side="right")
        cards.append((st, head, bal, sub, cv, rate))

    ctl = tk.Frame(root, bg=BG)
    ctl.pack(fill="x", padx=12, pady=(4, 10))
    tk.Label(ctl, text="Draw load from:", bg=BG, fg=DIM, font=mono).pack(side="left")
    sel = tk.StringVar(value=addrs[0])
    om = tk.OptionMenu(ctl, sel, *addrs)
    om.config(bg=PANEL, fg=FG, font=mono, relief="flat", highlightthickness=0)
    om.pack(side="left", padx=6)
    stat = tk.Label(ctl, text="idle", bg=BG, fg=DIM, font=mono)
    stat.pack(side="right")

    def toggle():
        if load.running():
            load.stop()
            btn.config(text="▶ Draw load")
            stat.config(text="idle", fg=DIM)
        else:
            host, _, port = sel.get().rpartition(":")
            load.start(host or "127.0.0.1", int(port or 9000))
            btn.config(text="■ Stop load")
            stat.config(text="drawing load — coins flowing", fg=GRN)

    btn = tk.Button(ctl, text="▶ Draw load", command=toggle, bg=ACC, fg="#fff",
                    font=mono, relief="flat", activebackground=GRN)
    btn.pack(side="left", padx=12)

    def tick():
        for st in states:
            st.poll()
        for (st, head, bal, sub, cv, rate) in cards:
            dot = "● online" if st.online else "○ offline"
            head.config(text=f"{st.addr}    {dot}    {st.account}",
                        fg=DIM if st.online else RED)
            flow = (f"   +{st.coin_delta}" if st.coin_delta > 0
                    else (f"   {st.coin_delta}" if st.coin_delta < 0 else ""))
            bal.config(text=f"{st.balance} CompuCoin{flow}",
                       fg=(GRN if st.coin_delta > 0
                           else (RED if st.coin_delta < 0 else FG)))
            sub.config(text=f"jobs {st.jobs}    chunks {st.chunks}    "
                            f"({st.balance} burnable → votes)")
            cps = st.chunks_per_sec()
            cv.delete("all")
            w = cv.winfo_width() or 320
            fill = max(0.0, min(1.0, cps / METER_FULL))
            if fill > 0:
                cv.create_rectangle(0, 0, int(w * fill), 14, fill=GRN, outline="")
            rate.config(text=f"{cps:.1f} ch/s")
        if load.running():
            stat.config(text=f"drawing load — {load.buys} buys, coins flowing",
                        fg=GRN)
        root.after(POLL_MS, tick)

    def on_close():
        load.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(300, tick)
    root.mainloop()


if __name__ == "__main__":
    main()
