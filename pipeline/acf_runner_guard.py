#!/usr/bin/env python3
"""acf_runner_guard — сторож самоподнятия CI-инфры aicontent-factory (t_ea04a09c).

Инцидент 12.11: контейнеры gh-runner-* удалены, scheduled workflows disabled_manually,
прогонов не было 10 дней, а разборы списывали простой на «мёртвые модели». Гард падает
(exit 1) с сигнатурами:
  RUNNERS_ZERO        — 0 online self-hosted раннеров в репо (total_count==0 или все offline);
  WORKFLOW_DISABLED   — у планового (schedule) workflow state != active;
  NO_RUNS_6H          — ни одного прогона за последние 6 ч при активных планировщиках;
  OWNING_SLOT_RATE    — green-доля слотов daily-owning за 7 дней < 90% (критерий замера
                        t_c3cb2ecb/t_c87cd624). Считается по ОЖИДАЕМЫМ слотам (2/день из
                        cron в workflow), поэтому молча пропущенный слот = провал, как и
                        красный run: приёмка «>=90% scheduled success» меряется непрерывно,
                        а не разовой карточкой.
Тихий прогон (0 сигнатур) = exit 0, одна строка ok. Алерт — в Telegram (TG_BOT_TOKEN/
TG_CHAT_ID[/TG_THREAD_ID]); без секретов — только печать.

Подмена gh для теста: env ACF_GUARD_GH=/path/to/stub (stub получает `api <path>`).
--dry-run только печатает. Тест: pipeline/test_acf_runner_guard.py.
"""
import datetime
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse
import urllib.request

REPO = "mytab0r/aicontent-factory"
STALE_H = 6
# Замер слота (t_c87cd624): scheduled-слоты daily-owning и порог приёмки.
RATE_WF = "daily-owning.yml"
RATE_SLOTS_PER_DAY = 2   # cron "0 15,21 * * *" в .github/workflows/daily-owning.yml
RATE_WINDOW_D = 7
RATE_MIN = 0.90
GH = os.environ.get("ACF_GUARD_GH", "gh")
STATE = pathlib.Path(os.environ.get("ACF_GUARD_STATE", "/opt/data/state/acf_runner_guard.state"))
WF_DIR = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"


def gh_json(path):
    r = subprocess.run([GH, "api", f"repos/{REPO}/{path}"], capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(f"gh api {path}: rc={r.returncode} {r.stderr[:200]}")
    return json.loads(r.stdout)


def scheduled_paths():
    """Имена файлов workflow с schedule-триггером из репо (по состоянию файлов на диске)."""
    out = set()
    for p in WF_DIR.glob("*.yml"):
        try:
            txt = p.read_text()
        except OSError:
            continue
        if "\nschedule:" in txt or txt.startswith("schedule:"):
            out.add(p.name)
    return out


def slot_rate_runs(now=None):
    """Schedule-прогоны RATE_WF за окно (gh api). Возвращает (runs, expected_slots)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    start = (now - datetime.timedelta(days=RATE_WINDOW_D)).date().isoformat()
    data = gh_json(f"actions/workflows/{RATE_WF}/runs?per_page=100&created=%3E%3D{start}")
    runs = [r for r in data.get("workflow_runs", []) if r.get("event") == "schedule"]
    return runs, RATE_SLOTS_PER_DAY * RATE_WINDOW_D


def check(runners, workflows, runs, now=None, sched=None, slots=None):
    """Чистая функция: (runners, workflows, runs[, slots]) -> список сигнатур. Тестируется без сети.

    slots = (schedule_runs_RATE_WF, expected_slots) — замер доли зелёных слотов; None = не мерить
    (gh не отдал данные — молчать нельзя, но и врать нулём нельзя: сигнал NO_RUNS_6H уже сработает).
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    sig = []
    online = [r for r in runners.get("runners", []) if r.get("status") == "online"]
    if runners.get("total_count", 0) == 0 or not online:
        sig.append("RUNNERS_ZERO")
    sched = sched if sched is not None else scheduled_paths()
    for w in workflows.get("workflows", []):
        name = w["path"].split("/")[-1]
        if name in sched and w["state"] != "active":
            sig.append(f"WORKFLOW_DISABLED {name}")
    newest = max((r["created_at"] for r in runs.get("workflow_runs", [])), default=None)
    if not newest or (now - datetime.datetime.fromisoformat(newest)) > datetime.timedelta(hours=STALE_H):
        sig.append(f"NO_RUNS_{STALE_H}H")
    if slots:
        slot_runs, expected = slots
        green = sum(1 for r in slot_runs if r.get("conclusion") == "success")
        if expected and green / expected < RATE_MIN:
            sig.append(f"OWNING_SLOT_RATE {green}/{expected} {100 * green / expected:.0f}%")
    return sig


def alert(text):
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
    except Exception as e:
        print(f"TG fail: {type(e).__name__}")
        return False


def main():
    try:
        runners = gh_json("actions/runners?per_page=100")
        workflows = gh_json("actions/workflows?per_page=100")
        runs = gh_json("actions/runs?per_page=50")
        slots = slot_rate_runs()
    except Exception as e:
        print(f"ALERT acf-runner-guard: gh слеп: {e}")
        alert(f"🚨 acf-runner-guard: gh api недоступен: {e}")
        return 2
    sig = check(runners, workflows, runs, slots=slots)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
    slot_runs, expected = slots
    green = sum(1 for r in slot_runs if r.get("conclusion") == "success")
    print(f"owning slots {RATE_WINDOW_D}d: green {green}/{expected}, fired {len(slot_runs)}")
    if not sig:
        print("ok: runners online, scheduled workflows active, runs fresh")
        return 0
    print("ALERT acf-runner-guard: " + "; ".join(sig))
    alert(f"🚨 acf-runner-guard: {'; '.join(sig)}. Диагностика: gh api repos/{REPO}/actions/runners")
    return 1


if __name__ == "__main__":
    sys.exit(main())
