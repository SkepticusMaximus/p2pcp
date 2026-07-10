"""p2pcp — a trustless peer-to-peer compute mesh with a mutual-credit ledger.

Strangers transact compute for CompuCoin over a plain TCP wire (SHA3-256 digests,
ed25519 signatures, JSON frames), with no coordinator and no company in the middle.
The core is pure stdlib + PyNaCl — no platform lock-in — so any machine can run a
node, buy compute, or sell its own via a bring-your-own callable (FunctionWorker).

Trust comes from replay, not reputation: for deterministic (native) work the buyer
re-runs the job and only pays if the bits match, so a forger is caught before a coin
moves. That verifiable work is also what earns a governance vote (§3/§10).
"""

from . import wire, organ, worker, ledger, consensus, daemon  # noqa: F401
from .daemon import Daemon
from .ledger import Identity, Ledger, VCLASS_NATIVE, VCLASS_FLOAT
from .worker import WorkerAdapter, DeterministicWorker, FunctionWorker

__all__ = [
    "wire", "organ", "worker", "ledger", "consensus", "daemon",
    "Daemon", "Identity", "Ledger", "WorkerAdapter", "DeterministicWorker",
    "FunctionWorker", "VCLASS_NATIVE", "VCLASS_FLOAT",
]
__version__ = "0.1.0"
