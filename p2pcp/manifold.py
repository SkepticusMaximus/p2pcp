"""p2pcp.manifold — the Vector Manifold: distributed training / weight-sharing.

A SECOND protocol riding the SAME P2PCP wire as a negotiated capability
(cap = "manifold") — NOT a separate port. A protocol is identified by its
handshake and its frame `type` tags, never by its port number, so this shares
one socket with the compute protocol and is routed by type; a stranger's P2P
network on the same port simply fails the P2PCP handshake and is dropped.

The payload is TernOO-native in intent (per the captain's ruling: it is the
Words, not the bytes — a non-ternary node cannot participate by proxy). This
module implements the mechanics in portable Python so they run and test on
their own; the TernOO seams — real PIGART rendering and MAP/I-O Word encoding
in the 5500fp tree — plug in at the marked boundaries (`render_ascii` stands in
for PIGART; `to_map_packets` structures the payload as MAP words already).

Pipeline (the captain's, 26-27/07):
  1. vector-as-object   a pattern is a graphable object: a typed curve per dim
  2. render             PIGART draws it (render_ascii here)
  3. packetise          ships as I/O words carrying MAP words (to_map_packets)
  4. DIF + rate         DIF against the local state, rate MMID vs MMOE
  5. re-stage           precision-weighted (Bayesian) merge; iterate

MMID = content identity of a manifold (SHA3-256 of its canonical form, matching
P2PCP's wire-digest). MMOE = Mismatch Of Expectation: how far an incoming
manifold diverges from what the local one predicts. Design memo:
TernOO-5500FP private/docs-bench/drafts/2026-07-27-vector-manifold-design-v0.1.md
"""

import hashlib
import json
import math

PROTOCOL = "p2pcp-manifold/0.1"
CAP = "manifold"                       # advertised in the node's caps at handshake

# ── curve kinds (each a typed function of a shared parameter t, e.g. train-step)
LINEAR = "linear"                      # y = a*t + b
POLY2 = "poly2"                        # y = a*t^2 + b*t + c
EXP = "exp"                            # y = a*exp(b*t)
KINDS = (LINEAR, POLY2, EXP)


# ── pure-Python least squares (no numpy; PyNaCl is p2pcp's only dependency) ───
def _solve(A, y):
    """Solve A x = y for a small square system by Gaussian elimination."""
    n = len(A)
    M = [row[:] + [y[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            raise ValueError("singular")
        M[col], M[piv] = M[piv], M[col]
        pivval = M[col][col]
        for r in range(n):
            if r == col:
                continue
            f = M[r][col] / pivval
            M[r] = [a - f * b for a, b in zip(M[r], M[col])]
    return [M[i][n] / M[i][i] for i in range(n)]


def _polyfit(ts, ys, degree):
    """Least-squares polynomial coefficients, highest power first."""
    p = degree + 1
    # normal equations (Vandermonde^T Vandermonde) x = Vandermonde^T y
    powers = [[t ** k for k in range(p)] for t in ts]
    A = [[sum(powers[i][a] * powers[i][b] for i in range(len(ts)))
          for b in range(p)] for a in range(p)]
    rhs = [sum(powers[i][a] * ys[i] for i in range(len(ts))) for a in range(p)]
    coef_low = _solve(A, rhs)           # low power first
    return coef_low[::-1]               # return high power first


def _residual(kind, coeffs, ts, ys):
    return math.fsum((eval_curve(kind, coeffs, t) - y) ** 2 for t, y in zip(ts, ys))


def eval_curve(kind, coeffs, t):
    if kind == LINEAR:
        a, b = coeffs
        return a * t + b
    if kind == POLY2:
        a, b, c = coeffs
        return a * t * t + b * t + c
    if kind == EXP:
        a, b = coeffs
        return a * math.exp(b * t)
    raise ValueError(f"unknown curve kind {kind!r}")


def fit_curve(ts, ys):
    """Fit the best of {linear, poly2, exp} to (ts, ys); return (kind, coeffs).

    'Best' = lowest sum-squared residual, with a mild complexity tie-break so a
    straight line is not beaten by a poly that only overfits noise."""
    ts, ys = list(map(float, ts)), list(map(float, ys))
    cands = []
    try:
        cands.append((LINEAR, _polyfit(ts, ys, 1)))
    except ValueError:
        pass
    if len(ts) >= 3:
        try:
            cands.append((POLY2, _polyfit(ts, ys, 2)))
        except ValueError:
            pass
    if all(y > 0 for y in ys) and len(ts) >= 2:      # exp needs positive y
        try:
            b, la = _polyfit(ts, [math.log(y) for y in ys], 1)  # log y = b t + la
            cands.append((EXP, [math.exp(la), b]))
        except (ValueError, OverflowError):
            pass
    if not cands:                                    # degenerate: constant
        return LINEAR, [0.0, ys[0] if ys else 0.0]
    scored = []
    for kind, coeffs in cands:
        r = _residual(kind, coeffs, ts, ys)
        penalty = 1e-9 * len(coeffs)                 # break ties toward simpler
        scored.append((r + penalty, kind, coeffs))
    scored.sort(key=lambda s: s[0])
    return scored[0][1], scored[0][2]


# ── the Manifold: a graphable object, one typed curve per named dimension ─────
class Manifold:
    """A pattern as a graphable object. `dims` maps a dimension name to a fitted
    (kind, coeffs) curve over a shared parameter axis. `confidence` is the
    precision (evidence weight) behind it — accumulated across re-stages, the
    Bayesian bookkeeping. `axis` is the (min,max) parameter range it was fit on."""

    def __init__(self, dims, confidence=1.0, axis=(0.0, 1.0), meta=None):
        self.dims = dict(dims)                       # name -> (kind, coeffs)
        self.confidence = float(confidence)
        self.axis = (float(axis[0]), float(axis[1]))
        self.meta = dict(meta or {})

    @classmethod
    def fit(cls, samples, confidence=1.0, meta=None):
        """samples: {dim_name: [(t, y), ...]} -> a fitted Manifold."""
        dims, lo, hi = {}, math.inf, -math.inf
        for name, pts in samples.items():
            ts = [float(t) for t, _ in pts]
            ys = [float(y) for _, y in pts]
            dims[name] = list(fit_curve(ts, ys))
            lo, hi = min(lo, *ts), max(hi, *ts)
        axis = (lo, hi) if dims else (0.0, 1.0)
        return cls(dims, confidence=confidence, axis=axis, meta=meta)

    def evaluate(self, name, t):
        kind, coeffs = self.dims[name]
        return eval_curve(kind, coeffs, t)

    def sample(self, name, n=16):
        lo, hi = self.axis
        if n < 2 or hi <= lo:
            return [self.evaluate(name, lo)]
        step = (hi - lo) / (n - 1)
        return [self.evaluate(name, lo + i * step) for i in range(n)]

    # ── serialization: canonical form + MMID (SHA3-256, P2PCP's wire digest) ──
    def canonical(self):
        body = {
            "protocol": PROTOCOL,
            "axis": [round(self.axis[0], 9), round(self.axis[1], 9)],
            "dims": {n: [k, [round(c, 9) for c in cf]]
                     for n, (k, cf) in sorted(self.dims.items())},
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()

    def mmid(self):
        """Content identity of the manifold — the wire MMID."""
        return hashlib.sha3_256(self.canonical()).hexdigest()

    def to_dict(self):
        return {"protocol": PROTOCOL, "confidence": self.confidence,
                "axis": list(self.axis),
                "dims": {n: [k, list(cf)] for n, (k, cf) in self.dims.items()},
                "meta": self.meta}

    @classmethod
    def from_dict(cls, d):
        dims = {n: [v[0], list(v[1])] for n, v in d["dims"].items()}
        return cls(dims, confidence=d.get("confidence", 1.0),
                   axis=d.get("axis", (0.0, 1.0)), meta=d.get("meta"))


# ── step 3: packetise as I/O words carrying MAP words ─────────────────────────
# A MAP word here = a spatial coordinate (the dimension name) + its curve payload.
# An I/O packet groups MAP words under a header. This mirrors the TernOO wire
# intent; the 5500fp encoder replaces the JSON body with real 24-trit Words.
def to_map_packets(manifold, per_packet=8):
    words = [{"map_coord": name, "curve": [k, [round(c, 9) for c in cf]]}
             for name, (k, cf) in sorted(manifold.dims.items())]
    packets, mmid = [], manifold.mmid()
    for i in range(0, max(1, len(words)), per_packet):
        packets.append({
            "io_header": {"mmid": mmid, "axis": list(manifold.axis),
                          "confidence": manifold.confidence,
                          "seq": len(packets)},
            "map_words": words[i:i + per_packet],
        })
    return packets


def from_map_packets(packets):
    dims, axis, conf = {}, (0.0, 1.0), 1.0
    for p in packets:
        h = p.get("io_header", {})
        axis = tuple(h.get("axis", axis))
        conf = h.get("confidence", conf)
        for w in p.get("map_words", []):
            k, cf = w["curve"]
            dims[w["map_coord"]] = [k, list(cf)]
    return Manifold(dims, confidence=conf, axis=axis)


# ── step 2 (render): PIGART stand-in — a tiny ASCII plot of each dim's curve ──
def render_ascii(manifold, width=40, height=7):
    """A stand-in for PIGART. Draws every dimension's curve on one grid, scaled
    to the shared range. The real renderer lives in 5500fp/ternoo_pigart.py."""
    if not manifold.dims:
        return "(empty manifold)"
    xs = [i / (width - 1) for i in range(width)]
    lo, hi = manifold.axis
    series = {n: [eval_curve(k, cf, lo + x * (hi - lo)) for x in xs]
              for n, (k, cf) in manifold.dims.items()}
    allv = [v for s in series.values() for v in s]
    vlo, vhi = min(allv), max(allv)
    span = (vhi - vlo) or 1.0
    grid = [[" "] * width for _ in range(height)]
    marks = "*+o#@x=~"
    for idx, (name, s) in enumerate(series.items()):
        m = marks[idx % len(marks)]
        for xi, v in enumerate(s):
            row = height - 1 - int((v - vlo) / span * (height - 1))
            grid[max(0, min(height - 1, row))][xi] = m
    legend = "  ".join(f"{marks[i % len(marks)]} {n}"
                       for i, n in enumerate(series))
    body = "\n".join("|" + "".join(r) for r in grid)
    return f"{body}\n+{'-' * width}\n{legend}   [{vlo:.3g}..{vhi:.3g}]"


# ── step 4: DIF + rate (MMID vs MMOE) ─────────────────────────────────────────
SAME, MOVED, NEW, GONE = "SAME", "MOVED", "NEW", "GONE"


def _divergence(local, incoming, name, n=16):
    """Normalised RMS divergence of `incoming`'s curve from `local`'s over the
    shared axis — the per-dimension Mismatch Of Expectation."""
    a = local.sample(name, n)
    b = incoming.sample(name, n)
    scale = (max(map(abs, a)) or 1.0)
    rms = math.sqrt(math.fsum((x - y) ** 2 for x, y in zip(a, b)) / len(a))
    return rms / scale


def dif(local, incoming, tol=1e-6):
    """Per-dimension change report between two manifolds."""
    out = {}
    for name in set(local.dims) | set(incoming.dims):
        if name in local.dims and name in incoming.dims:
            d = _divergence(local, incoming, name)
            out[name] = {"status": SAME if d <= tol else MOVED, "delta": d}
        elif name in incoming.dims:
            out[name] = {"status": NEW, "delta": math.inf}
        else:
            out[name] = {"status": GONE, "delta": math.inf}
    return out


def rate(local, incoming):
    """Rate an incoming manifold against the local one.

    MMID: do the content identities match (byte-identical pattern)?
    MMOE: mean expectation-mismatch over shared dimensions.
    alignment: 1 / (1 + mean shared divergence)  ∈ (0, 1], 1.0 iff identical."""
    d = dif(local, incoming)
    shared = [v["delta"] for v in d.values() if v["status"] in (SAME, MOVED)]
    mmoe = (math.fsum(shared) / len(shared)) if shared else math.inf
    alignment = 1.0 if not shared else 1.0 / (1.0 + mmoe)
    return {
        "mmid_local": local.mmid(),
        "mmid_incoming": incoming.mmid(),
        "mmid_match": local.mmid() == incoming.mmid(),
        "mmoe": mmoe,
        "alignment": alignment,
        "dif": d,
    }


# ── step 5: re-stage (precision-weighted / Bayesian merge; iterate) ───────────
def restage(local, incoming, rating=None, samples=16):
    """Merge `incoming` into `local`, precision-weighted by confidence and
    discounted by alignment (a first-cut poisoning brake: a wildly divergent
    peer earns less trust). Returns a NEW Manifold; iterating converges toward
    agreement. New confidence = local + trusted incoming (evidence accumulates)."""
    r = rating or rate(local, incoming)
    align = r["alignment"]
    lc, ic = local.confidence, incoming.confidence * align   # discounted evidence
    total = lc + ic or 1.0
    w = ic / total                                           # Bayesian blend weight
    lo = min(local.axis[0], incoming.axis[0])
    hi = max(local.axis[1], incoming.axis[1])
    axis = (lo, hi)
    step = (hi - lo) / (samples - 1) if samples > 1 and hi > lo else 0.0
    xs = [lo + i * step for i in range(samples)] if step else [lo]

    new_dims = {}
    for name in set(local.dims) | set(incoming.dims):
        if name in local.dims and name in incoming.dims:
            ys = [(1 - w) * eval_curve(*local.dims[name], t)
                  + w * eval_curve(*incoming.dims[name], t) for t in xs]
            new_dims[name] = list(fit_curve(xs, ys))
        elif name in incoming.dims:                          # adopt new dim, hedged
            new_dims[name] = list(incoming.dims[name])
        else:
            new_dims[name] = list(local.dims[name])           # keep dim peer lacks
    return Manifold(new_dims, confidence=lc + ic, axis=axis,
                    meta={**local.meta, "restaged_from": r["mmid_incoming"][:12]})
