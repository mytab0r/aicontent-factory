"""Общие утилиты пайплайна: вызов 9router, пути, работа с состоянием."""
import http.client
import json
import os
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
STATE_DIR = ROOT / ".state"


def router_base_url() -> str:
    return os.environ.get("ROUTER_BASE_URL", "http://172.18.0.10:20128/v1")


def router_api_key() -> str:
    key = os.environ.get("ROUTER_API_KEY")
    if key:
        return key
    # fallback: достаём из контейнера hermes (ключ не хранится в репо/.env проекта)
    out = subprocess.run(
        ["docker", "exec", "hermes", "printenv", "ROUTER_API_KEY"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def router_post(path: str, payload: dict, timeout: int = 120, retries: int = 3) -> dict:
    url = f"{router_base_url()}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {router_api_key()}",
            "Content-Type": "application/json",
        },
    )
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            last_err = RuntimeError(f"9router {path} HTTP {e.code}: {body}")
            # 429/503 — временная перегрузка провайдера, стоит повторить
            if e.code in (429, 503) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise last_err from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            # DNS/timeout/TLS/оборванный ответ (IncompleteRead) — тоже RuntimeError, чтобы фолбэки шагов 01/02 срабатывали
            last_err = RuntimeError(f"9router {path} network: {e}")
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise last_err from None
    raise last_err


def load_moods() -> list[str]:
    """Простой парсер config/moods.yaml (список строк под ключом moods:), без pyyaml (YAGNI)."""
    path = ROOT / "config" / "moods.yaml"
    moods = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- "):
            moods.append(line[2:].strip())
    return moods


def rotate(name: str, n: int, state_dir: Path | None = None) -> int:
    """Индекс ротации .state/<name>_idx.txt (коммитится CI): вернуть текущий, сдвинуть."""
    d = state_dir or STATE_DIR
    d.mkdir(exist_ok=True)
    f = d / f"{name}_idx.txt"
    idx = int(f.read_text()) if f.exists() else 0
    f.write_text(str(idx + 1))
    return idx % n


def next_mood() -> str:
    moods = load_moods()
    return moods[rotate("mood", len(moods))]


def tg_send(text: str) -> bool:
    """Сообщение в Telegram (TG_BOT_TOKEN/TG_CHAT_ID[/TG_THREAD_ID] из секретов CI).
    Без секретов — печать и False: отчёт не должен валить выпуск."""
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    print(f"TG: {text}")
    if not token or not chat:
        print("TG skip: нет TG_BOT_TOKEN/TG_CHAT_ID")
        return False
    import urllib.parse
    data = {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}
    if os.environ.get("TG_THREAD_ID"):
        data["message_thread_id"] = os.environ["TG_THREAD_ID"]
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage",
                               data=urllib.parse.urlencode(data).encode(), timeout=20)
        return True
    except Exception as e:  # не светим токен из URL
        print(f"TG fail: {type(e).__name__}")
        return False


def new_run_dir() -> Path:
    import datetime
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def latest_run_dir() -> Path:
    runs = sorted(RUNS_DIR.glob("*"))
    if not runs:
        raise SystemExit("нет ни одного запуска в runs/ — сначала выполнить 01_idea.py")
    return runs[-1]
