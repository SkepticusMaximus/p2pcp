"""p2pcp.node — the library behind the standalone CLI.

Everything here is generic: a node sells compute from ANY worker adapter (bring
your own callable via FunctionWorker, or the built-in DeterministicWorker demo)
and buys compute from other nodes, replay-auditing native work before it pays.
No platform-specific models — those are plugins that drop in behind WorkerAdapter.
"""

import hashlib
import json
import os
import signal
import threading
import time

from . import daemon as D
from . import worker as WK

L = D.L                                    # the ledger module (Identity, Ledger, …)

AUTOSAVE_SECS = 3                           # how often a running node flushes its ledger


def _raise_kbd(*_):
    """SIGTERM handler → raise KeyboardInterrupt in the main thread, so a managed
    stop (systemctl stop / SIGTERM) unwinds through serve()'s finally and flushes
    the ledger, exactly like Ctrl-C does."""
    raise KeyboardInterrupt


def identity_from_seed(seed):
    """A stable identity from a seed phrase (repeatable runs). Production nodes
    persist an ed25519 key instead — see load_or_create_identity."""
    if isinstance(seed, str):
        seed = seed.encode("utf-8")
    return L.Identity.from_seed(hashlib.sha256(seed).digest())


def load_or_create_identity(path):
    """A node's PERSISTENT identity: load its ed25519 key from `path`, or create
    and save one (owner-only perms). A node keeps its account — and its earned
    CompuCoin — across restarts."""
    if os.path.exists(path):
        with open(path) as f:
            return L.Identity.from_seed(bytes.fromhex(f.read().strip()))
    idn = L.Identity.generate()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(bytes(idn.signing_key).hex())
    return idn


def node_identity(seed=None, keyfile=None):
    return load_or_create_identity(keyfile) if keyfile else identity_from_seed(
        seed or "node")


def parse_peers(peers_csv):
    """'host:port,host:port' -> [(host, port), ...]."""
    out = []
    for item in (peers_csv or "").split(","):
        item = item.strip()
        if not item:
            continue
        host, _, port = item.rpartition(":")
        out.append((host or "127.0.0.1", int(port)))
    return out


def join_mesh(node, peers):
    """Seed the peer book from bootstrap peers, then discover more (a dead seed is
    skipped). Returns the peer count now known."""
    for host, port in peers:
        node.add_peer(host, port)
    for host, port in peers:
        try:
            node.fetch_peers(host, port)
        except Exception:                  # a dead seed is not fatal
            pass
    return len(node.known_peers())


# ── the worker you sell (bring your own) ─────────────────────────────────────

def load_worker(spec, vclass=None):
    """Resolve a worker to SELL. `spec` is one of:
      * None or "demo"  -> the built-in DeterministicWorker (a native, replay-class
                           testnet worker: output is a pure SHA3 fold of the job).
      * "module:callable" -> import that module, wrap the callable as a
                           FunctionWorker. Declare vclass honestly: native only if
                           the function is deterministic and bit-exactly reproducible
                           (any peer can replay-audit it); float otherwise.
    """
    vc = WK.VCLASS_FLOAT if vclass == "float" else WK.VCLASS_NATIVE
    if not spec or spec == "demo":
        return WK.DeterministicWorker()
    import importlib
    mod_name, _, fn_name = spec.partition(":")
    if not fn_name:
        raise ValueError("worker spec must be 'module:callable'")
    fn = getattr(importlib.import_module(mod_name), fn_name)
    return WK.FunctionWorker(fn, vclass=vc)


def _load_verified_ledger(ledger_path):
    """Load a persisted ledger and REFUSE it if integrity fails (§5) — a poisoned
    dump must not mint balance or franchise. Absent file -> a fresh empty ledger."""
    if not os.path.exists(ledger_path):
        return L.Ledger()
    ledger = L.Ledger.load(ledger_path)
    if not ledger.verify():
        raise ValueError(f"ledger integrity check failed: {ledger_path}")
    return ledger


def serve(worker, host="127.0.0.1", port=0, seed="node", keyfile=None, peers=None,
          label="node"):
    """Run a worker node until interrupted — it sells compute for CompuCoin.
    `keyfile` persists identity + earnings + peer book across restarts; `peers`
    bootstraps into a mesh."""
    identity = node_identity(seed, keyfile)
    ledger_path = (keyfile + ".ledger") if keyfile else None
    ledger = None
    if ledger_path and os.path.exists(ledger_path):
        ledger = L.Ledger.load(ledger_path)
        if not ledger.verify():
            print(f"[{label}] REFUSING TO START: ledger integrity check failed "
                  f"({ledger_path})", flush=True)
            return
    node = D.Daemon(identity, worker=worker, ledger=ledger)
    h, p = node.start(host, port)
    peers_path = (ledger_path + ".peers") if ledger_path else None
    if peers_path and os.path.exists(peers_path):
        node.load_peers(peers_path)
    print(f"[{label}] listening on {h}:{p}", flush=True)
    print(f"[{label}] account {node.account_id.hex()[:16]}… — selling compute "
          f"({'native' if worker.vclass == WK.VCLASS_NATIVE else 'float'})",
          flush=True)
    if peers:
        join_mesh(node, peers)
    if peers or (peers_path and os.path.exists(peers_path)):
        print(f"[{label}] mesh: know {len(node.known_peers())} peer(s)", flush=True)
    # Persist earnings WHILE running, not only on a clean exit. A systemd service
    # never reached the old finally-only save, so earnings stayed in RAM and the
    # separate `wallet` process always read 0. (1) autosave the ledger whenever it
    # changes; (2) treat SIGTERM (systemctl stop) like Ctrl-C so a managed stop
    # also flushes.
    stop_autosave = threading.Event()

    def _autosave():
        last = -1
        while not stop_autosave.wait(AUTOSAVE_SECS):
            rev = node.ledger_rev()
            if rev != last:
                try:
                    node.save_ledger(ledger_path)
                    last = rev
                except Exception:              # a transient FS error must not kill the node
                    pass
    if ledger_path:
        threading.Thread(target=_autosave, name="p2pcp-autosave",
                         daemon=True).start()
    try:
        signal.signal(signal.SIGTERM, _raise_kbd)
    except (ValueError, OSError):
        pass                                   # not main thread / platform quirk — non-fatal

    print(f"[{label}] Ctrl-C to stop.", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop_autosave.set()
        node.stop()
        if ledger_path:
            node.save_ledger(ledger_path)      # final flush, under the chain lock
        if peers_path:
            node.save_peers(peers_path)
        earned = (node.ledger.balance(node.account_id)
                  if node.account_id in node.ledger.chains else 0)
        print(f"\n[{label}] stopped. earned {earned} CompuCoin.", flush=True)


# ── buying compute ───────────────────────────────────────────────────────────

MODEL_BUY_TIMEOUT = 240.0     # float work = real inference; give the model time
NATIVE_BUY_TIMEOUT = 15.0


def buy(job, host=None, port=None, peers=None, chunks=1, k=3, vclass="native",
        audit_worker="demo", seed="buyer", timeout=None):
    """Buy compute. Native work is REPLAY-AUDITED with `audit_worker` (the same
    callable the seller runs) — you pay only for chunks you re-derive bit-for-bit.
    Float work is taken on trust of quorum (audit=None). Give a specific `host`/
    `port`, or `peers` to discover a provider for the class and fall through if one
    is down. Returns (client_daemon, served_addr_or_None, result)."""
    vc = L.VCLASS_FLOAT if vclass == "float" else L.VCLASS_NATIVE
    audit = None if vc == L.VCLASS_FLOAT else load_worker(audit_worker,
                                                          vclass=vclass)
    if timeout is None:      # a model needs thinking time; the demo answers instantly
        timeout = MODEL_BUY_TIMEOUT if vc == L.VCLASS_FLOAT else NATIVE_BUY_TIMEOUT
    client = D.Daemon(identity_from_seed(seed), timeout=timeout)
    job_bytes = job if isinstance(job, (bytes, bytearray)) else str(job).encode()
    if peers:
        cap = "compute:float" if vc == L.VCLASS_FLOAT else "compute:native"
        addr, res = client.buy_from_mesh(cap, job_bytes, chunks, k, vc,
                                         audit=audit, candidates=peers)
        return client, addr, res
    res = client.request_job(host, int(port), job_bytes, n_chunks=chunks, k=k,
                             vclass=vc, audit=audit)
    return client, (host, int(port)), res


# ── read-only views ──────────────────────────────────────────────────────────

def wallet(keyfile, now=None):
    """A node's account + CompuCoin, read from its persisted state — no server.
    `balance` is spendable; `weight_bearing` is burnable; `weight` is the decayed
    voting weight already burned (§10)."""
    if not os.path.exists(keyfile):
        raise FileNotFoundError(f"no node key at {keyfile}")
    acct = load_or_create_identity(keyfile).account_id
    ledger = _load_verified_ledger(keyfile + ".ledger")
    nw = int(time.time()) if now is None else now
    if acct in ledger.chains:
        return {"account": acct.hex(), "balance": ledger.balance(acct),
                "weight_bearing": ledger.burnable(acct),
                "weight": ledger.weight(acct, nw)}
    return {"account": acct.hex(), "balance": 0, "weight_bearing": 0, "weight": 0.0}


def burn(keyfile, amount, now=None):
    """Burn earned weight-bearing credit into governance weight (§10), persisted.
    Only replay-class earnings can be burned. Returns the wallet after burning."""
    if not os.path.exists(keyfile):
        raise FileNotFoundError(f"no node key at {keyfile}")
    identity = load_or_create_identity(keyfile)
    ledger_path = keyfile + ".ledger"
    ledger = _load_verified_ledger(ledger_path)
    nw = int(time.time()) if now is None else now
    if identity.account_id not in ledger.chains:
        ledger.open_account(identity)
    ledger.burn(identity, int(amount), timestamp=nw, now=nw)
    ledger.save(ledger_path)
    return wallet(keyfile, now=nw)


def node_status(host, port, seed="observer"):
    """A node's public status (worker classes, caps, peers, jobs served)."""
    return D.Daemon(identity_from_seed(seed)).fetch_status(host, int(port))


def find_providers(cap, peers, seed="finder"):
    """Scan `peers` for nodes advertising compute class `cap` (compute:native /
    compute:float). Returns matching (host, port)."""
    return D.Daemon(identity_from_seed(seed)).find_providers(cap, peers)
