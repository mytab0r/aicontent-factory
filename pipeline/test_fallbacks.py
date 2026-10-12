#!/usr/bin/env python3
"""Фолбэки ежедневного выпуска: падение внешнего сервиса не валит выпуск.

Запуск: python3 pipeline/test_fallbacks.py
- router_post: сетевая ошибка (DNS/timeout) -> RuntimeError (ловится фолбэками)
- 01_idea: все LLM упали -> детерминированная идея по шаблону + ротация .state
- 02_cover: image API упал -> локальная обложка (PIL), 1024x1024
- 03_music: ACE на ПК недоступен -> HF Space
"""
import importlib.util
import os
import sys
import tempfile
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace(".", "_"), HERE / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_router_network_error_is_runtime():
    os.environ["ROUTER_API_KEY"] = "x"
    orig, osleep = common.urllib.request.urlopen, common.time.sleep

    def boom(*a, **k):
        raise urllib.error.URLError("Temporary failure in name resolution")

    common.urllib.request.urlopen, common.time.sleep = boom, lambda s: None
    try:
        common.router_post("/chat/completions", {}, retries=2)
    except RuntimeError as e:
        assert "network" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
    finally:
        common.urllib.request.urlopen, common.time.sleep = orig, osleep


def test_rotate_advances_and_wraps():
    with tempfile.TemporaryDirectory() as d:
        got = [common.rotate("t", 3, Path(d)) for _ in range(4)]
        assert got == [0, 1, 2, 0], got


def test_fallback_idea_valid_and_varies():
    idea_mod = load("01_idea.py")
    with tempfile.TemporaryDirectory() as d:
        a = idea_mod.fallback_idea("anime lofi", Path(d))
        b = idea_mod.fallback_idea("anime lofi", Path(d))
    for i in (a, b):
        assert set(i) >= {"mood", "cover_prompt", "title", "description", "tags"}, i
        assert 0 < len(i["title"]) <= 70, i["title"]
        assert len(i["tags"]) >= 8
    assert a["title"] != b["title"], "шаблон должен ротироваться (anti-template)"


def test_idea_main_survives_router_down():
    idea_mod = load("01_idea.py")

    def down(*a, **k):
        raise RuntimeError("9router 503")

    idea_mod.router_post = down
    with tempfile.TemporaryDirectory() as d:
        idea_mod.new_run_dir = lambda: Path(d)
        idea_mod.STATE_DIR = Path(d) / ".state"
        os.environ["GENRE"] = "anime lofi"
        idea_mod.main()
        assert (Path(d) / "idea.json").exists()


def test_fallback_cover_png():
    cover = load("02_cover.py")
    from PIL import Image

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "cover.png"
        cover.fallback_cover("rainy tokyo night", out)
        im = Image.open(out)
        assert im.size == (1024, 1024)
        assert im.resize((8, 8)).getextrema() != ((im.getpixel((0, 0))[0],) * 2,) * 3 and im.getpixel((0, 0)) != im.getpixel((0, 1023)), "не однотонная заливка"


def test_ace_local_down_falls_back_to_space():
    music = load("03_music.py")
    calls = []

    class FakeClient:
        def __init__(self, src, token=None):
            calls.append(src)
            if src.startswith("http://ace-step"):
                raise ConnectionError("Name or service not known")

        def predict(self, **k):
            return ["/tmp/x.mp3"]

    os.environ["ACE_ENDPOINT"] = "http://ace-step:7865/"
    try:
        assert music.generate_track("p", 30, client_cls=FakeClient) == "/tmp/x.mp3"
    finally:
        del os.environ["ACE_ENDPOINT"]
    assert calls == ["http://ace-step:7865/", music.SPACE], calls


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
