"""p2pcp.model_worker — sell a real local model's inference on the mesh.

A P2PCP worker is just ``fn(job: bytes, index: int) -> bytes``. These adapters
forward the job (a prompt) to a local model backend and return its answer, so

    p2pcp serve --worker p2pcp.model_worker:ollama --float --keyfile K

sells real inference for CompuCoin. LLM output is not bit-reproducible, so it is
**float class** (earns spendable rent, never a replay-audit or a vote — that
distinction is the whole point of §3). A deterministic ternary model (Bonsai)
could instead be native-class; that's a design-seat call, not baked in here.

One thin harness, any backend — pick the callable, configure with env vars:

  echo    no deps. A deterministic transform of the prompt, to prove the plumbing
          without a model installed.
  ollama  POST {OLLAMA_URL:-http://127.0.0.1:11434}/api/generate
          env: OLLAMA_URL, OLLAMA_MODEL (default "llama3").
  openai  POST {OPENAI_BASE:-http://127.0.0.1:1234}/v1/chat/completions — the
          OpenAI-compatible shape that llama.cpp-server / LM Studio / vLLM / real
          OpenAI all speak. env: OPENAI_BASE, OPENAI_MODEL, OPENAI_KEY.

Stdlib only (urllib) — no new dependency. A backend error propagates, so the node
sends worker-halt and the buyer pays nothing for a broken answer.
"""
import json
import os
import urllib.request

HTTP_TIMEOUT = float(os.environ.get("P2PCP_MODEL_TIMEOUT", "120"))


def _post_json(url, payload, headers=None):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _prompt(job, index):
    p = job.decode("utf-8", "replace")
    return p if not index else f"{p}\n(variant {index})"


def echo(job: bytes, index: int) -> bytes:
    """No-backend test model: proves the harness + wire without a model running."""
    return f"[echo#{index}] {job.decode('utf-8', 'replace')}".encode("utf-8")


def ollama(job: bytes, index: int) -> bytes:
    """Sell an Ollama model's inference. `ollama serve` must be running locally."""
    url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3")
    r = _post_json(url + "/api/generate",
                   {"model": model, "prompt": _prompt(job, index), "stream": False})
    return (r.get("response") or "").encode("utf-8")


def openai(job: bytes, index: int) -> bytes:
    """Sell inference from any OpenAI-compatible local server (llama.cpp, LM
    Studio, vLLM, …) — one adapter for the whole family."""
    base = os.environ.get("OPENAI_BASE", "http://127.0.0.1:1234").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "local-model")
    key = os.environ.get("OPENAI_KEY", "not-needed")
    r = _post_json(base + "/v1/chat/completions",
                   {"model": model,
                    "messages": [{"role": "user", "content": _prompt(job, index)}]},
                   headers={"Authorization": f"Bearer {key}"})
    return r["choices"][0]["message"]["content"].encode("utf-8")
