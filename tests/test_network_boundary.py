"""test_network_boundary.py — the ONE-ORGAN network invariant, package-wide.

Spec: P2PCP §1.5. Engelbart's rule made mechanical: the network is the operator's
limb hanging off ONE controlling organ, never a promiscuous surface. Exactly one
module in the ``p2pcp`` package may import the network; every other module is
forbidden, and CI proves it by walking the imports (AST, not a string grep — a
scan-string like ``'import socket'`` inside a guard test is not an import).

The one organ is ``organ.py`` (the socket module). This test keeps every other
module honest forever after: if a second socket ever appears in a worker adapter,
the daemon, or anywhere else in the package, it fails here.

Run: ``python3 -m unittest discover -s tests``
"""

import ast
import os
import unittest

# ── the network surface: top-level modules that touch the wire ───────────────
# A module importing any of these is "network-facing". Kept broad on purpose.
NETWORK_MODULES = {
    "socket", "socketserver", "ssl", "select", "selectors",
    "http", "urllib", "ftplib", "telnetlib", "smtplib", "poplib",
    "imaplib", "nntplib", "xmlrpc", "asyncio",
    # third-party clients, should any ever be added
    "requests", "aiohttp", "httpx", "websockets", "websocket", "zmq",
}

# ── the ONE organ (§1.5) ─────────────────────────────────────────────────────
# Package module names permitted to import the network. Exactly one: `organ`
# (the socket module, p2pcp/organ.py). The `<= 1` assertion below is Engelbart's
# one-limb rule, enforced by CI: you cannot grow a second organ.
NETWORK_ALLOWLIST = {"organ"}   # the ONE organ (§1.5)

# Bridges: network-facing by nature, but OUTSIDE the trustless core, so exempt from
# the one-organ rule. `gateway` is the optional WebSocket<->TCP bridge for browser
# clients — it must exist to span two transports. Its exemption is safe only because
# it is a DUMB, keyless pipe: it imports no ledger/consensus/daemon, holds no key,
# and shuttles opaque frames, so it cannot forge a receipt or spend a coin. That
# "dumb pipe" property is itself asserted below, so the exemption can't be abused.
# `model_worker` is the same species on the other side: a backend ADAPTER that
# forwards a job to the operator's OWN local model server (Ollama / an OpenAI-
# compatible llama.cpp) over localhost HTTP. It never speaks the P2PCP wire — not
# a second mesh organ — and like gateway it is keyless and trust-free (imports no
# ledger/consensus/daemon/worker), which the same assertion below proves for it.
BRIDGE_EXEMPT = {"gateway", "model_worker"}
TRUST_MODULES = {"ledger", "consensus", "daemon", "worker"}  # keys / money / protocol

# The package scanned — the whole p2pcp package, not one module.
_HERE = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.join(os.path.dirname(_HERE), "p2pcp")


def _top(mod):
    return (mod or "").split(".")[0]


def _network_imports(path):
    """The set of network top-level modules imported by a file (AST-exact — a
    string literal that merely spells 'import socket' is not an import)."""
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if _top(a.name) in NETWORK_MODULES:
                    found.add(_top(a.name))
        elif isinstance(node, ast.ImportFrom):
            # level>0 is a relative (in-package) import — never the stdlib net.
            if node.level == 0 and _top(node.module) in NETWORK_MODULES:
                found.add(_top(node.module))
    return found


def _module_stem(path):
    return os.path.splitext(os.path.basename(path))[0]


class TestNetworkBoundary(unittest.TestCase):
    """The network arrives as one narrow, auditable organ (spec §1.5)."""

    def test_exactly_one_organ_allowed(self):
        # Engelbart's one-limb rule, mechanical: the allow-list can never name a
        # second network-importing module. A trusted/second surface that exists
        # anywhere is a downgrade target everywhere (§2.2).
        self.assertLessEqual(
            len(NETWORK_ALLOWLIST), 1,
            "at most ONE module may import the network (§1.5); "
            f"allow-list has {len(NETWORK_ALLOWLIST)}: {sorted(NETWORK_ALLOWLIST)}")

    def test_no_module_outside_the_allowlist_imports_the_network(self):
        offenders = {}
        for dp, _dirs, files in os.walk(PKG_DIR):
            if "__pycache__" in dp:
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(dp, f)
                if _module_stem(path) in NETWORK_ALLOWLIST | BRIDGE_EXEMPT:
                    continue
                nets = _network_imports(path)
                if nets:
                    offenders[_module_stem(path)] = sorted(nets)
        self.assertEqual(
            offenders, {},
            "modules outside the one-organ allow-list import the network "
            f"(§1.5): {offenders}. Only `organ` may touch the wire; otherwise the "
            "limb has grown a second head.")

    def test_bridges_are_dumb_keyless_pipes(self):
        # A bridge's network exemption is only safe if it carries NO trust logic:
        # importing the ledger/consensus/daemon/worker would give it keys or protocol
        # authority it could abuse. Prove each exempt bridge imports none of them.
        for name in BRIDGE_EXEMPT:
            path = os.path.join(PKG_DIR, name + ".py")
            self.assertTrue(os.path.isfile(path), f"exempt bridge {name!r} missing")
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            trust = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level > 0:
                    if _top(node.module) in TRUST_MODULES:
                        trust.add(_top(node.module))
            self.assertEqual(
                trust, set(),
                f"bridge {name!r} imports trust modules {sorted(trust)} — a bridge "
                "must be a dumb, keyless pipe to keep its network exemption safe.")

    def test_the_one_organ_actually_imports_the_network(self):
        # A stale allow-list entry (organ renamed/removed) silently disables the
        # guard. Prove the allow-listed organ exists AND really is the socket
        # surface — so `organ` is the ONLY module importing socket, and it does.
        for name in NETWORK_ALLOWLIST:
            path = os.path.join(PKG_DIR, name + ".py")
            self.assertTrue(os.path.isfile(path),
                            f"allow-listed organ {name!r} does not exist")
            self.assertIn("socket", _network_imports(path),
                          f"allow-listed organ {name!r} imports no network module")


if __name__ == "__main__":
    unittest.main()
