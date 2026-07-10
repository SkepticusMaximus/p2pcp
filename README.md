# p2pcp — a trustless compute mesh

Your computer can do small compute jobs for strangers and get paid in **CompuCoin**,
and pay other computers to do jobs for you — with no company in the middle taking a
cut or holding the money. It's a market of stalls trading directly.

Trust comes from **replay, not reputation**: for deterministic (native) work the
buyer re-runs the job itself and only pays if the bits match, so a cheat is caught
before a coin moves. That same verifiable work is what earns a governance vote.

The core is pure Python — standard library plus [PyNaCl](https://pynacl.readthedocs.io)
for ed25519. SHA3-256 digests and JSON frames over one TCP socket. No GPU, no
account, no platform lock-in. This package is the platform-agnostic core extracted
from the [TernOO-5500FP](https://github.com/) project, where it began.

## Install

```
pip install -e .          # from a checkout (PyNaCl is the only dependency)
```

## Quickstart — two terminals

Sell compute (a worker node — leave it running):

```
p2pcp serve --port 9000                 # sells the built-in demo worker
```

Buy compute from it:

```
p2pcp buy "any payload" --port 9000 --chunks 3 --k 2
```

You pay per delivered, verified chunk. The demo worker is deterministic, so your
side **replay-audits** every chunk before paying — try pointing `buy` at a node that
lies and you simply won't be charged.

## Sell your own compute

The demo worker is a stand-in. To sell real work, hand `serve` any callable
`fn(job: bytes, index: int) -> bytes`:

```
p2pcp serve --worker mypkg.mymod:my_fn --port 9000            # native (default)
p2pcp serve --worker mypkg.mymod:my_llm --float --port 9001  # not bit-reproducible
```

Declare the class **honestly**: `native` only if the function is deterministic and
bit-exactly reproducible (any peer can replay-audit it and it earns a governance
vote); `--float` otherwise (it earns money, checked by redundancy, never a vote).

## Wallet and governance

```
p2pcp serve --port 9000 --keyfile ~/.p2pcp/node.key   # persists identity + earnings
p2pcp wallet --keyfile ~/.p2pcp/node.key              # balance, burnable, voting weight
p2pcp burn   --keyfile ~/.p2pcp/node.key --amount 5   # earned credit -> a vote
```

Only replay-class (native) earnings can be burned into voting weight, so a vote
always traces back to auditable work.

## Find a provider instead of naming one

Nodes advertise which class they serve, so you can discover one:

```
p2pcp find --class native --peers 127.0.0.1:9000,127.0.0.1:9001
p2pcp buy "job" --peers 127.0.0.1:9000,127.0.0.1:9001    # picks one, skips any that are down
p2pcp status --port 9000
```

## Cross-box and cloud

The wire is byte-identical to loopback — run `serve` on one machine and
`buy --host <ip>` from another. A headless node runs anywhere:

```
docker build -t p2pcp .
docker run --rm -p 9000:9000 p2pcp serve --host 0.0.0.0 --port 9000
```

## How the trust works

One paid job, chunk by chunk:

1. buyer → seller: **JOB** (the payload)
2. seller → buyer: **RESULT** (the output)
3. buyer re-runs the job itself and checks the output matches — *pay only if it does*
4. buyer → seller: **RECEIPT** (a signed IOU for `k` CompuCoin)
5. seller → buyer: **ACK** (co-signed) → the coin settles

Exposure is bounded to one chunk, and a forged result is refused at step 3 before
payment. Float work (which can't be re-run bit-for-bit) rides redundancy instead.

## In the browser

A browser can't open a raw socket, so it reaches the mesh through the WebSocket
gateway and buys with a small JS client that speaks the wire byte-for-byte with the
Python core (same canonical JSON, SHA3-256 digests, ed25519 signatures — a Python
seller accepts a browser's receipts). Keys stay in the tab; the gateway is a dumb,
keyless pipe.

```
pip install 'p2pcp[gateway]'
p2pcp-gateway --port 8800                 # the WebSocket <-> TCP bridge
# then serve a float seller and open web/index.html in a browser
```

`web/p2pcp.js` is the client (buyer); `web/index.html` is a demo page. A browser is
buyer/light-only — it can't listen for inbound jobs, so it never sells. Interop is
proven in `tests/test_js_interop.py`: the JS canon/digest/signing bytes match Python
exactly, and a real Node buyer settles a float job through the gateway.

## The one organ

Exactly one module — `p2pcp/organ.py` — is allowed to import the network. Every
other module is forbidden, and a test (`tests/test_network_boundary.py`) proves it
by walking the imports. The network is a single narrow, auditable surface.

## Run the tests

```
python3 -m unittest discover -s tests -p 'test_*.py'
```

## Status

v0.1 core, extracted standalone and green (142 tests on loopback). Runs three ways:
a native node (`p2pcp`), a headless cloud node (Docker), and an in-browser buyer
(gateway + `web/`). **License:** GNU GPL v3 or later — see [LICENSE](LICENSE).
