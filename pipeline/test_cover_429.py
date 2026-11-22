#!/usr/bin/env python3
"""t_629a7ba2: 27-28.10 gpt-image-1.5 отдавал 429 -> 02_cover ставил заглушку -> 04b FAIL «обложка-заглушка».
При 429 обязаны сработать: ретрай по «reset after Ns» -> другая модель -> банк артов; заглушка только без фолбэков.

t_2b4f5dec: flux-1-schnell теперь первичная модель (gpt-image-1.5 401 invalidated oauth).
Тесты обновлены под новый порядок: flux primary, gpt-image fallback."""
import importlib.util, json, os, sys, tempfile, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import quality_gate as qg

# 429 теперь приходит от codex/gpt-image-1.5 даже когда запрос к flux (роутер маршрутизирует через codex)
LIMIT_FLUX = '9router /images/generations HTTP 429: {"error":{"message":"[codex/gpt-image-1.5] [429]: The usage limit has been reached (reset after 6s)"}}'
LIMIT_GPT = '9router /images/generations HTTP 429: {"error":{"message":"[codex/gpt-image-1.5] [429]: The usage limit has been reached (reset after 6s)"}}'


def load(d, router_post):
    sys.modules["common"] = types.SimpleNamespace(router_post=router_post, latest_run_dir=lambda: d)
    spec = importlib.util.spec_from_file_location("cover429", Path(__file__).parent / "02_cover.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.time = types.SimpleNamespace(sleep=lambda s: sleeps.append(s))
    return m


def png_b64():
    import base64, io
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (64, 36), (120, 90, 160)).save(b, "JPEG")  # flux отдаёт JPEG
    return base64.b64encode(b.getvalue()).decode()


def run(case, router_post, bank=True):
    global sleeps
    sleeps = []
    td = tempfile.mkdtemp()
    d = Path(td)
    (d / "idea.json").write_text(json.dumps({"cover_prompt": "Night Train window"}), encoding="utf-8")
    os.environ["ACF_COVER_BANK"] = str(Path(__file__).resolve().parent.parent / "assets" / "cover_bank") if bank else str(d / "none")
    load(d, router_post).main()
    src = json.loads((d / "cover_source.json").read_text(encoding="utf-8"))
    print(case, src["path"], src.get("model") or src.get("file") or "", "sleeps", sleeps)
    return d, src


calls = []
def always_429(path, body, timeout=0):
    calls.append(body["model"])
    raise RuntimeError(LIMIT_FLUX)

for genre in ("anime lofi", "chill phonk"):
    os.environ["GENRE"] = genre
    calls.clear()
    d, src = run(f"[{genre}] всё 429 ->", always_429)
    assert src["path"] == "bank", src
    assert calls.count("cf/@cf/black-forest-labs/flux-1-schnell") == 2, calls  # первичная модель + один ретрай по reset after
    assert any("gpt-image" in c for c in calls), "не переключился на fallback"
    assert sleeps == [8, 8], sleeps  # по одному ретраю (6s+2) на каждую модель
    assert not (d / "cover_fallback.json").exists() and qg.fallback_why(d) == [], "банк есть, а стоит заглушка"
    from PIL import Image
    assert Image.open(d / "cover.png").size[0] >= 1024, "из банка пришла не обложка"
    assert qg.cover_why(d / "cover.png") == [], qg.cover_why(d / "cover.png")  # V9 яркость

# 429 на первой (flux), повтор после reset — успех
n = []
def ok_after_retry(path, body, timeout=0):
    n.append(1)
    if len(n) == 1:
        raise RuntimeError(LIMIT_FLUX)
    return {"data": [{"b64_json": png_b64()}]}
_, src = run("429 -> ретрай ->", ok_after_retry)
assert src["path"] == "retry" and src["model"] == "cf/@cf/black-forest-labs/flux-1-schnell", src

# flux 429 с длинным окном -> сразу gpt-image
def flux_long_gpt_ok(path, body, timeout=0):
    if "flux" in body["model"]:
        raise RuntimeError(LIMIT_FLUX.replace("6s", "15m 51s"))
    assert "size" in body, "gpt-image требует size"
    return {"data": [{"b64_json": png_b64()}]}
_, src = run("429 долгий -> fallback ->", flux_long_gpt_ok)
assert src["path"] == "fallback_model" and "gpt-image" in src["model"] and sleeps == [], (src, sleeps)

# без банка и без моделей — прежний V14: заглушка + маркер (04b не пропустит)
d, src = run("всё 429, банк пуст ->", always_429, bank=False)
assert src["path"] == "placeholder" and qg.fallback_why(d), src

# t_2b4f5dec: 401/403/404/408 не должны жечь лимиты ретраями — сразу дальше по цепочке
AUTH_401 = '9router /images/generations HTTP 401: {"error":{"message":"[codex/gpt-image-1.5] [401]: Encountered invalidated oauth token for user, failing request (reset after 6s)"}}'
auth_calls = []
def auth_401_all(path, body, timeout=0):
    auth_calls.append(body["model"])
    raise RuntimeError(AUTH_401)

# flux 401, gpt-image ok -> fallback_model без лишних повторений flux
n_flux = []
def flux_401_gpt_ok(path, body, timeout=0):
    if "flux" in body["model"]:
        n_flux.append(body["model"])
        raise RuntimeError(AUTH_401)
    assert "size" in body, "gpt-image требует size"
    return {"data": [{"b64_json": png_b64()}]}

os.environ["GENRE"] = "anime lofi"
d, src = run("401 -> gpt-image ->", flux_401_gpt_ok)
assert src["path"] == "fallback_model" and "gpt-image" in src["model"], src
assert n_flux.count("cf/@cf/black-forest-labs/flux-1-schnell") == 1, n_flux  # flux не принимает size, один вызов без ретраев на 401
assert qg.fallback_why(d) == []

# все 401 -> банк
os.environ["GENRE"] = "anime lofi"
d, src = run("401 всё -> банк ->", auth_401_all)
assert src["path"] == "bank", src
assert qg.fallback_why(d) == []

# все 401, банк пуст -> заглушка
d, src = run("401 всё, банк пуст ->", auth_401_all, bank=False)
assert src["path"] == "placeholder" and qg.fallback_why(d), src

print("test_cover_429 OK")
