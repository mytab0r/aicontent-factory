#!/usr/bin/env python3
"""t_629a7ba2: 27-28.10 gpt-image-1.5 отдавал 429 -> 02_cover ставил заглушку -> 04b FAIL «обложка-заглушка».
При 429 обязаны сработать: ретрай по «reset after Ns» -> другая модель -> банк артов; заглушка только без фолбэков."""
import importlib.util, json, os, sys, tempfile, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import quality_gate as qg

LIMIT = '9router /images/generations HTTP 429: {"error":{"message":"[codex/gpt-image-1.5] [429]: The usage limit has been reached (reset after 6s)"}}'

# t_60cce439: canvas fixed as nvidia:flux_2-klein-4b + openrouter:gemini-2.5-flash-image
NVIDIA = "nvidia:flux_2-klein-4b"
OPENROUTER = "openrouter:gemini-2.5-flash-image"
GPT = "cx/gpt-image-1.5"
FLUX = "cf/@cf/black-forest-labs/flux-1-schnell"

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
    raise RuntimeError(LIMIT)

for genre in ("anime lofi", "chill phonk"):
    os.environ["GENRE"] = genre
    calls.clear()
    d, src = run(f"[{genre}] всё 429 ->", always_429)
    assert src["path"] == "bank", src
    assert all(c in (GPT, NVIDIA, OPENROUTER) for c in calls), calls
    assert sleeps == [8, 8], sleeps  # по одному ретраю (6s+2) на каждую модель
    assert not (d / "cover_fallback.json").exists() and qg.fallback_why(d) == [], "банк есть, а стоит заглушка"
    from PIL import Image
    assert Image.open(d / "cover.png").size[0] >= 1024, "из банка пришла не обложка"
    assert qg.cover_why(d / "cover.png") == [], qg.cover_why(d / "cover.png")  # V9 яркость

# t_60cce439: new canvas = nvidia:flux_2-klein-4b + openrouter:gemini-2.5-flash-image
# 2 jobs in daily-video: both models exhausted; expect fallback to bank.
# 429 on first model, retry after reset — success
n = []
def ok_after_retry(path, body, timeout=0):
    n.append(1)
    if len(n) == 1:
        raise RuntimeError(LIMIT)
    return {"data": [{"b64_json": png_b64()}]}
_, src = run("429 -> retry ->", ok_after_retry)
assert src["path"] == "retry" and src["model"] == NVIDIA, src

# first model 429 long window -> immediate fallback to second model
# t_60cce439: second model (gemini) DOES accept size (unlike flux-1-schnell)
def gpt_long_flux_ok(path, body, timeout=0):
    if "flux_2-klein" in body["model"]:
        raise RuntimeError(LIMIT.replace("6s", "15m 51s"))
    # second model (gemini) accepts size
    return {"data": [{"b64_json": png_b64()}]}
_, src = run("429 long -> fallback to gemini ->", gpt_long_flux_ok)
assert src["path"] == "fallback_model" and "gemini" in src["model"] and sleeps == [], (src, sleeps)

# без банка и без моделей — прежний V14: заглушка + маркер (04b не пропустит)
d, src = run("всё 429, банк пуст ->", always_429, bank=False)
assert src["path"] == "placeholder" and qg.fallback_why(d), src

# t_2b4f5dec: 401/403/404/408 не должны жечь лимиты ретраями — сразу дальше по цепочке
AUTH_401 = '9router /images/generations HTTP 401: {"error":{"message":"[codex/gpt-image-1.5] [401]: Encountered invalidated oauth token for user, failing request (reset after 6s)"}}'
auth_calls = []
def auth_401_all(path, body, timeout=0):
    auth_calls.append(body["model"])
    raise RuntimeError(AUTH_401)

# t_60cce439: new canvas = nvidia:flux_2-klein-4b + openrouter:gemini-2.5-flash-image
# first model 401, second model ok -> fallback_model without extra retries
n_gpt = []
def gpt_401_flux_ok(path, body, timeout=0):
    if NVIDIA in body["model"]:
        n_gpt.append(body["model"])
        raise RuntimeError(AUTH_401)
    # second model (gemini) accepts size
    return {"data": [{"b64_json": png_b64()}]}

os.environ["GENRE"] = "anime lofi"
d, src = run("401 -> gemini ->", gpt_401_flux_ok)
assert src["path"] == "fallback_model" and "gemini" in src["model"], src
assert n_gpt.count(NVIDIA) == 1, n_gpt  # one attempt (no size), no retries on 401
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
