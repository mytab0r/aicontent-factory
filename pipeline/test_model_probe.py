#!/usr/bin/env python3
"""t_b87507e0: probe живучести модели до генерации + retry 5xx + fallback на следующую модель.

Запуск: python3 pipeline/test_model_probe.py
- 404/400 (model_not_found / unsupported) -> probe False, полный запрос не уходит, берём следующую модель
- 503/5xx -> router_post ретраит с backoff, после исчерпания probe False -> следующая модель
- все модели мертвы -> llm_idea/llm_translate отдают понятную ошибку (имя модели в тексте)
"""
import http.server
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("ROUTER_API_KEY", "x")

import common


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace(".", "_"), HERE / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def http_err(code):
    return RuntimeError(f"9router /chat/completions HTTP {code}: body")


def boom(code):
    def f(*a, **k):
        raise http_err(code)
    return f


# ---------- model_alive ----------

def test_probe_dead_statuses():
    """404/400/503 после ретраев = мёртвая модель, probe False."""
    for code in (404, 400, 503):
        assert common.model_alive("m", post=boom(code)) is False, code


def test_probe_live_and_cheap():
    seen = {}

    def post(path, payload, **kw):
        seen.update(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    assert common.model_alive("m", post=post) is True
    assert seen["max_tokens"] <= 32, seen


# ---------- retry 5xx внутри router_post ----------

class _Srv:
    """Локальный 9router: отдаёт заданные коды по порядку, дальше 200."""

    def __init__(self, codes, body=None):
        self.codes, self.hits, self.body = list(codes), [], body or {"ok": 1}
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                code = outer.codes.pop(0) if outer.codes else 200
                outer.hits.append(code)
                data = json.dumps(outer.body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = http.server.ThreadingHTTPServer(("", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://{socket.gethostname()}:{self.srv.server_address[1]}"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.srv.shutdown()


def test_5xx_retries_then_succeeds():
    slept, orig_sleep = [], common.time.sleep
    common.time.sleep = lambda s: slept.append(s)
    try:
        with _Srv([503, 500]) as s:
            os.environ["ROUTER_BASE_URL"] = s.url
            assert common.router_post("/chat/completions", {}) == {"ok": 1}
            assert s.hits == [503, 500, 200], s.hits
    finally:
        common.time.sleep = orig_sleep
        os.environ.pop("ROUTER_BASE_URL", None)
    assert slept == [5, 10], slept  # backoff растёт


def test_5xx_exhausted_probe_false():
    """Провайдер лежит (500 x3) -> probe False, цепочка идёт следующей модели."""
    orig_sleep = common.time.sleep
    common.time.sleep = lambda s: None
    try:
        with _Srv([500, 500, 500]) as s:
            os.environ["ROUTER_BASE_URL"] = s.url
            assert common.model_alive("sleepy-model") is False
            assert len(s.hits) == 3, s.hits
    finally:
        common.time.sleep = orig_sleep
        os.environ.pop("ROUTER_BASE_URL", None)


# ---------- fallback в 01_idea ----------

def test_llm_idea_skips_dead_and_uses_live():
    idea_mod = load("01_idea.py")
    idea_mod.MODELS = ["dead-404", "throw-400", "live"]
    calls = []

    def fake_post(path, payload, **kw):
        calls.append((payload["model"], payload.get("max_tokens")))
        if payload["model"].startswith(("dead-404", "throw-400")):
            raise http_err(404 if payload["model"] == "dead-404" else 400)
        return {"choices": [{"message": {"content": '{"title": "x"}'}}]}

    idea_mod.router_post = fake_post
    out, err = idea_mod.llm_idea("prompt")
    assert err is None and out == {"title": "x"}, (out, err)
    assert [c for c in calls if c[0] == "dead-404"] == [("dead-404", 16)], calls
    assert [c for c in calls if c[0] == "throw-400"] == [("throw-400", 16)], calls
    assert calls[-1] == ("live", 1500), calls


def test_llm_idea_all_dead_names_model():
    idea_mod = load("01_idea.py")
    idea_mod.MODELS = ["dead-a", "dead-b"]
    idea_mod.router_post = boom(404)
    out, err = idea_mod.llm_idea("prompt")
    assert out is None and err is not None, (out, err)
    assert "dead-b" in str(err), err  # имя модели в ошибке, а не «None»


def test_owning_idea_skips_dead():
    """CHANNEL=owning: мёртвая модель пропускается до генерации скрипта."""
    idea_mod = load("01_idea.py")
    import owning_channel as oc
    calls = []

    def fake_post(path, payload, **kw):
        calls.append((payload["model"], payload.get("max_tokens")))
        if payload["model"] == "dead-404":
            raise http_err(404)
        return {"choices": [{"message": {"content": '{"hook": "h", "lines": ["a"]}'}}]}

    with tempfile.TemporaryDirectory() as td:
        idea_mod.MODELS = ["dead-404", "live"]
        idea_mod.router_post = fake_post
        idea_mod.STATE_DIR = Path(td)
        idea_mod.new_run_dir = lambda: Path(td)
        oc.next_plan = lambda d: {"topic": "t", "slot": 1}
        oc.idea_prompt = lambda p: "prompt"
        oc.validate_script = lambda d: d
        oc.parse_json = json.loads
        idea_mod.owning_idea()
        idea = json.loads((Path(td) / "idea.json").read_text())
    assert [c for c in calls if c[0] == "dead-404"] == [("dead-404", 16)], calls
    assert ("live", 4000) in calls, calls
    assert idea["channel"] == "owning", idea


# ---------- fallback в localize ----------

def _with_common_post(fake, fn):
    """localize берёт router_post из common внутри llm_translate — патчим common, не модуль."""
    orig = common.router_post
    common.router_post = fake
    try:
        return fn()
    finally:
        common.router_post = orig


def test_llm_translate_skips_dead():
    lz = load("localize.py")
    lz.MODELS = ["dead-404", "live"]
    calls = []

    def fake_post(path, payload, **kw):
        calls.append((payload["model"], payload.get("max_tokens")))
        if payload["model"] == "dead-404":
            raise http_err(404)
        return {"choices": [{"message": {"content": json.dumps({"title": "T", "description": "D", "lines": ["a"]})}}]}

    src = {"title": "T", "description": "D", "lines": ["a"]}
    out = _with_common_post(fake_post, lambda: lz.llm_translate(src, "es"))
    assert out == src, out
    assert [c for c in calls if c[0] == "dead-404"] == [("dead-404", 16)], calls
    assert calls[-1] == ("live", 6000), calls


def test_llm_translate_all_dead_raises():
    lz = load("localize.py")
    lz.MODELS = ["dead-a"]

    def fail():
        try:
            lz.llm_translate({"title": "T", "description": "D", "lines": ["a"]}, "es")
        except RuntimeError as e:
            assert "dead-a" in str(e), e
        else:
            raise AssertionError("ожидали RuntimeError")

    _with_common_post(boom(404), fail)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("all model probe tests passed")
