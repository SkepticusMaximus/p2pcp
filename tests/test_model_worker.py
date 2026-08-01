"""Tests for the model harness. `echo` runs for real; `ollama`/`openai` are
exercised against a stubbed HTTP layer so we verify the request shape and reply
parsing without a live model server."""
import json
import io

from p2pcp import model_worker as MW


def test_echo_transforms_prompt():
    out = MW.echo(b"hello mesh", 0)
    assert out == b"[echo#0] hello mesh"
    assert MW.echo(b"x", 2) == b"[echo#2] x"


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _stub(monkey_payloads, capture):
    """Return a fake urlopen that records the request and replies canned JSON."""
    def fake_urlopen(req, timeout=None):
        capture["url"] = req.full_url
        capture["body"] = json.loads(req.data.decode())
        capture["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _FakeResp(json.dumps(monkey_payloads).encode())
    return fake_urlopen


def test_ollama_request_and_parse(monkeypatch=None):
    cap = {}
    import urllib.request
    orig = urllib.request.urlopen
    urllib.request.urlopen = _stub({"response": "42 in ternary is 1110"}, cap)
    try:
        import os
        os.environ["OLLAMA_MODEL"] = "bonsai"
        out = MW.ollama(b"what is 42?", 0)
    finally:
        urllib.request.urlopen = orig
    assert out == b"42 in ternary is 1110"
    assert cap["url"].endswith("/api/generate")
    assert cap["body"]["model"] == "bonsai"
    assert cap["body"]["prompt"] == "what is 42?"
    assert cap["body"]["stream"] is False


def test_openai_request_and_parse():
    cap = {}
    import urllib.request
    orig = urllib.request.urlopen
    urllib.request.urlopen = _stub(
        {"choices": [{"message": {"content": "a balanced-ternary answer"}}]}, cap)
    try:
        out = MW.openai(b"explain trits", 0)
    finally:
        urllib.request.urlopen = orig
    assert out == b"a balanced-ternary answer"
    assert cap["url"].endswith("/v1/chat/completions")
    assert cap["body"]["messages"][0]["content"] == "explain trits"
    assert "authorization" in cap["headers"]


if __name__ == "__main__":
    import traceback
    ok = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        try:
            t(); print(f"  [PASS] {t.__name__}"); ok += 1
        except Exception:
            print(f"  [FAIL] {t.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(tests)} model-worker tests passed")
    raise SystemExit(0 if ok == len(tests) else 1)
