#!/usr/bin/env python3
"""Тест acf_runner_guard (t_ea04a09c): негативные кейсы — гард обязан падать с сигнатурой.

Кейс 4 (end-to-end) — ровно по карточке: подмена `gh api` стабом с total_count:0 →
guard exit!=0 и сигнатура RUNNERS_ZERO в выводе.
"""
import json
import os
import subprocess
import sys
import tempfile
import datetime
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import acf_runner_guard as g  # noqa: E402

NOW = datetime.datetime(2026, 11, 22, 18, 0, tzinfo=datetime.timezone.utc)
SCHED = {"daily-owning.yml", "post-analytics.yml"}
OK_RUNNERS = {"total_count": 1, "runners": [{"name": "pc-acf-release", "status": "online"}]}
OK_WF = {"workflows": [{"path": ".github/workflows/daily-owning.yml", "state": "active"},
                       {"path": ".github/workflows/post-analytics.yml", "state": "active"}]}
OK_RUNS = {"workflow_runs": [{"created_at": (NOW - datetime.timedelta(hours=1)).isoformat()}]}


def case_healthy():
    assert g.check(OK_RUNNERS, OK_WF, OK_RUNS, now=NOW, sched=SCHED) == []


def case_zero_runners():
    sig = g.check({"total_count": 0, "runners": []}, OK_WF, OK_RUNS, now=NOW, sched=SCHED)
    assert sig == ["RUNNERS_ZERO"], sig
    # все offline — то же самое: раннер есть в списке, но джобу взять некому
    off = {"total_count": 1, "runners": [{"name": "pc-acf-release", "status": "offline"}]}
    assert g.check(off, OK_WF, OK_RUNS, now=NOW, sched=SCHED) == ["RUNNERS_ZERO"]


def case_disabled_workflow():
    wf = {"workflows": [{"path": ".github/workflows/daily-owning.yml", "state": "disabled_manually"},
                        {"path": ".github/workflows/post-analytics.yml", "state": "active"},
                        # ручной одноразовый workflow выключен — не сигнал
                        {"path": ".github/workflows/oneoff-thing.yml", "state": "disabled_manually"}]}
    assert g.check(OK_RUNNERS, wf, OK_RUNS, now=NOW, sched=SCHED) == ["WORKFLOW_DISABLED daily-owning.yml"]


def case_stale_runs():
    old = {"workflow_runs": [{"created_at": (NOW - datetime.timedelta(hours=7)).isoformat()}]}
    assert g.check(OK_RUNNERS, OK_WF, old, now=NOW, sched=SCHED) == ["NO_RUNS_6H"]
    assert g.check(OK_RUNNERS, OK_WF, {"workflow_runs": []}, now=NOW, sched=SCHED) == ["NO_RUNS_6H"]


def case_e2e_stub_gh():
    """Стаб вместо gh: runners=0 → exit!=0 + RUNNERS_ZERO; здоровые фикстуры → exit 0."""
    with tempfile.TemporaryDirectory() as td:
        stub = pathlib.Path(td, "gh")
        stub.write_text(f"""#!/bin/sh
case "$2" in
  *actions/runners*) cat <<'J'
{json.dumps({"total_count": 0, "runners": []})}
J
  ;;
  *actions/workflows*) cat <<'J'
{json.dumps(OK_WF)}
J
  ;;
  *) cat <<'J'
{json.dumps(OK_RUNS)}
J
  ;;
esac
""")
        stub.chmod(0o755)
        env = dict(os.environ, ACF_GUARD_GH=str(stub), ACF_GUARD_STATE=str(pathlib.Path(td, "state")))
        env.pop("TG_BOT_TOKEN", None)
        env.pop("TG_CHAT_ID", None)
        r = subprocess.run([sys.executable, g.__file__], capture_output=True, text=True, env=env, timeout=120)
        assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
        assert "RUNNERS_ZERO" in r.stdout, r.stdout
        print("e2e stub output:", r.stdout.strip())

        stub.write_text(stub.read_text().replace('"total_count": 0', '"total_count": 1')
                        .replace('"runners": []', '"runners": [{"name": "pc-acf-release", "status": "online"}]'))
        r = subprocess.run([sys.executable, g.__file__], capture_output=True, text=True, env=env, timeout=120)
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


for fn in (case_healthy, case_zero_runners, case_disabled_workflow, case_stale_runs, case_e2e_stub_gh):
    fn()
    print("ok", fn.__name__)
print("ALL OK")
