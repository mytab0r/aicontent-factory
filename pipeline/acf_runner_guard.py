#!/usr/bin/env python3
"""acf_runner_guard — сторож самоподнятия CI-инфры aicontent-factory (t_ea04a09c).

Инцидент 12.11: контейнеры gh-runner-* удалены, scheduled workflows disabled_manually,
прогонов не было 10 дней, а разборы списывали простой на «мёртвые модели». Гард падает
(exit 1) с сигнатурами:
  RUNNERS_ZERO        — 0 online self-hosted раннеров в репо (total_count==0 или все offline);
  WORKFLOW_DISABLED   — у планового (schedule) workflow state != active;
  NO_RUNS_6H          — ни одного прогона за последние 6 ч при активных планировщиках.
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


def check(runners, workflows, runs, now=None, sched=None):
    """Чистая функция: (runners, workflows, runs) -> список сигнатур. Тестируется без сети."""
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
    except Exception as e:
        print(f"ALERT acf-runner-guard: gh слеп: {e}")
        alert(f"🚨 acf-runner-guard: gh api недоступен: {e}")
        return 2
    sig = check(runners, workflows, runs)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
    if not sig:
        print("ok: runners online, scheduled workflows active, runs fresh")
        return 0
    print("ALERT acf-runner-guard: " + "; ".join(sig))
    alert(f"🚨 acf-runner-guard: {'; '.join(sig)}. Диагностика: gh api repos/{REPO}/actions/runners")
    return 1


if __name__ == "__main__":
    sys.exit(main())
