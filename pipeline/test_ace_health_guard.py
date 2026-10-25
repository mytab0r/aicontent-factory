#!/usr/bin/env python3
"""t_50f1fc9b: «ace-step не healthy за N мин» (19.10, 5+ прогонов daily-video).
Причина (docs/forensics-t_03efb867.md): host disk-guard.ps1 `container prune` удалил остановленный ace-step,
затем `image prune -a` его образ. Тест падает, если вернётся любое звено класса:
- disk-guard снова чистит контейнеры/образы без проверки ace-step;
- daily-video не пересоздаёт удалённый контейнер;
- таймаут health молча падает без статуса и логов контейнера."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github/workflows"
GUARD = (ROOT / "deploy/gpu-pc/host/disk-guard.ps1").read_text(encoding="utf-8")


def guard_problems():
    bad = []
    for line in GUARD.splitlines():
        if "container prune" in line and "ace-step" not in line:
            bad.append("container prune без проверки ace-step running: " + line.strip())
    m = re.search(r"docker inspect ace-step[^\n]*\n\s*if \(\$LASTEXITCODE -eq 0\) \{ docker image prune -a", GUARD)
    if "image prune -a" in GUARD and not m:
        bad.append("image prune -a без проверки существования ace-step")
    return bad


def diag_problems():
    bad = []
    for f in sorted(WF.glob("*.y*ml")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "ace-step не healthy" in line and not ("State.Status" in line and "docker logs" in line):
                bad.append(f"{f.name}:{n}: таймаут health без статуса/логов ace-step")
    return bad


def test_disk_guard_spares_ace_step():
    assert guard_problems() == [], guard_problems()


def test_health_timeout_dumps_diagnostics():
    assert diag_problems() == [], diag_problems()


def test_daily_video_recreates_missing_ace_step():
    s = (WF / "daily-video.yml").read_text(encoding="utf-8")
    up = s[s.index("name: ACE-Step up"):s.index("name: 03 music")]
    assert "if ! docker inspect ace-step" in up and "docker run -d --name ace-step" in up


def test_checks_catch_regression():
    global GUARD
    saved = GUARD
    GUARD = "docker container prune -f --filter until=24h\ndocker image prune -a -f --filter until=72h\n"
    try:
        assert len(guard_problems()) == 2
    finally:
        GUARD = saved


if __name__ == "__main__":
    test_disk_guard_spares_ace_step()
    test_health_timeout_dumps_diagnostics()
    test_daily_video_recreates_missing_ace_step()
    test_checks_catch_regression()
    print("ok test_ace_health_guard")
