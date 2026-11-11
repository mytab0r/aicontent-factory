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


# ---------- t_c3cb2ecb: preflight + skipped slot ----------

def test_preflight_logs_all_models():
    def post(path, payload, **kw):
        if payload["model"] == "dead":
            raise RuntimeError("9router HTTP 404")
        return {"choices": [{"message": {"content": "ok"}}]}

    st = common.preflight(["alive", "dead"], post=post)
    assert st == {"alive": True, "dead": False}


def test_owning_idea_skips_with_exit3_when_all_models_fail():
    idea_mod = load("01_idea.py")

    def dead(*a, **k):
        return False

    idea_mod.model_alive = dead
    idea_mod.router_post = dead  # preflight тоже через него
    with tempfile.TemporaryDirectory() as d:
        idea_mod.STATE_DIR = Path(d)
        try:
            idea_mod.owning_idea()
        except SystemExit as e:
            assert e.code == 3, f"ожидался exit 3 (skipped slot), получил {e.code}"
        else:
            raise AssertionError("owning_idea должен завершать слот exit 3, не падать")


def test_owning_idea_bad_script_falls_to_next_model():
    """Пустой скрипт (combo content=None) не роняет run — валидный ответ на следующей модели."""
    idea_mod = load("01_idea.py")
    import owning_channel as oc
    import json as _json

    plan = {"topic": "car wash", "hook": "hook text", "structure": "list"}

    def set_plan(*a, **k):
        return dict(plan)

    oc.next_plan = set_plan
    run_dir = Path(tempfile.mkdtemp())
    idea_mod.STATE_DIR = Path(tempfile.mkdtemp())
    idea_mod.new_run_dir = lambda: run_dir
    oc.validate_script = lambda s: s
    idea_mod.model_alive = lambda *a, **k: True
    responses = iter([
        {"choices": [{"message": {"content": None}}]},  # combo: content=None -> AttributeError
        {"choices": [{"message": {"content": _json.dumps(
            {"title": "The Economics of Owning a car wash", "beats": [{"say": "a", "big": "b"}]})}}]},
        # на случай probe/повторного запроса третьей модели
        {"choices": [{"message": {"content": _json.dumps(
            {"title": "The Economics of Owning a car wash", "beats": [{"say": "a", "big": "b"}]})}}]},
    ])
    idea_mod.router_post = lambda *a, **k: next(responses)
    idea_mod.owning_idea()  # без SystemExit: второй ответ валиден, idea.json записан
    assert (run_dir / "idea.json").exists()


def test_owning_idea_all_empty_scripts_skip_not_crash():
    """41542127792-паттерн: combo отдаёт пустой скрипт всем моделям -> exit 3, не AttributeError."""
    idea_mod = load("01_idea.py")
    import owning_channel as oc

    def set_plan(*a, **k):
        return {"topic": "car wash", "hook": "hook text", "structure": "list"}

    oc.next_plan = set_plan
    idea_mod.STATE_DIR = Path(tempfile.mkdtemp())
    idea_mod.model_alive = lambda *a, **k: True
    idea_mod.router_post = lambda *a, **k: {"choices": [{"message": {"content": None}}]}
    try:
        idea_mod.owning_idea()
    except SystemExit as e:
        assert e.code == 3
    else:
        raise AssertionError("ожидался exit 3 при пустых скриптах всех моделей")



def test_dead_models_removed_from_chains():
    """t_b87507e0: glm (404 нет кредов) и cx/gpt-5.5 (400 unsupported) мертвы на 9router — не в цепочках."""
    idea_mod = load("01_idea.py")
    loc_mod = load("localize.py")
    for chain in (idea_mod.MODELS, loc_mod.MODELS):
        assert "glm/glm-5.3-flash" not in chain, chain
        assert "cx/gpt-5.5" not in chain, chain


def test_llm_idea_falls_through_model_chain():
    """t_b87507e0: probe мёртвой модели (404) -> сразу следующая; генерация только у живой."""
    idea_mod = load("01_idea.py")
    calls = []

    def fake_router_post(path, payload, **kw):
        calls.append((payload["model"], payload.get("max_tokens")))
        if payload["model"] == idea_mod.MODELS[0]:
            raise RuntimeError("9router HTTP 404: model_not_found")
        return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    idea_mod.router_post = fake_router_post
    idea_mod.MODELS = ["dead-model", "live-model"]
    out, err = idea_mod.llm_idea("prompt")
    assert err is None and out == {"ok": True}, (out, err)
    # мёртвая не получает полный запрос: только probe (16 токенов), затем probe+генерация живой
    assert [c for c in calls if c[0] == "dead-model"] == [("dead-model", 16)], calls
    assert calls[-2:] == [("live-model", 16), ("live-model", 1500)], calls


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


def test_frame_full_bleed_no_black_bars():
    """Обложка любого формата заполняет кадр 1920x1080 целиком (без чёрных полей; V8 25.10)."""
    from PIL import Image
    asm = load("04_assemble.py")
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "c.png", Path(d) / "f.png"
        Image.new("RGB", (1024, 1024), (200, 120, 60)).save(src)
        asm.burn_overlay(src, out)
        im = Image.open(out).convert("RGB")
        assert im.size == (1920, 1080), im.size
        for xy in [(0, 0), (1919, 0), (0, 540), (1919, 540), (960, 5)]:
            assert im.getpixel(xy) != (0, 0, 0), (xy, im.getpixel(xy))


def test_cover_prompt_has_channel_style():
    """Единый стиль канала: к любому промпту добавляется фиксированный STYLE."""
    cover = load("02_cover.py")
    assert cover.STYLE in cover.styled("girl by window")
    assert cover.SIZE == "1536x1024"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)

# ---- шаг 3 (t_c678b8fa): cover-стиль по жанру ----
cover_mod = load("02_cover.py")
os.environ["GENRE"] = "chill phonk"
_p = cover_mod.styled("Neon Highway at Midnight, night drive")
assert "night drive phonk" in _p and "anime lofi illustration" not in _p, _p
os.environ["GENRE"] = "anime lofi"
_p2 = cover_mod.styled("Rainy Tokyo street, anime girl at window")
assert "anime lofi illustration" in _p2 and "phonk" not in _p2.lower(), _p2
os.environ.pop("GENRE")
print("ok cover style per genre")
