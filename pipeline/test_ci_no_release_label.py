#!/usr/bin/env python3
"""t_55108370: label release = полоса выпусков (daily-video). 23.10 четыре прогона CI держали оба
release-раннера ~40 мин, плановый выпуск встал бы за ними. Ни один job ci.yml не должен брать
release-раннер: CI живёт на своём label ci. Запуск: python3 pipeline/test_ci_no_release_label.py"""
import re
from pathlib import Path

CI = Path(__file__).resolve().parent.parent / ".github/workflows/ci.yml"


def release_jobs(text):
    """-> имена jobs, чей runs-on содержит label release."""
    bad, job = [], None
    for line in text.splitlines():
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            job = m.group(1)
        m = re.match(r"^    runs-on:\s*(.+)$", line)
        if m and re.search(r"\brelease\b", m.group(1).split("#")[0]):
            bad.append(job)
    return bad


def test_selfcheck():
    assert release_jobs("jobs:\n  a:\n    runs-on: [self-hosted, release]\n") == ["a"]
    assert release_jobs("jobs:\n  a:\n    runs-on: [self-hosted, ci]  # не release\n") == []


def test_ci_jobs_not_on_release():
    text = CI.read_text(encoding="utf-8")
    assert re.search(r"^    runs-on:", text, re.M), "ci.yml: нет runs-on"
    bad = release_jobs(text)
    assert not bad, f"ci.yml jobs на release-раннере (полоса выпусков): {bad}"


def test_daily_video_slots_by_hermes_cron():
    """R1: слоты daily-video диспатчит cron Hermes; GitHub schedule опаздывает 6-9 ч / пропускает слот."""
    wf = (CI.parent / "daily-video.yml").read_text(encoding="utf-8")
    assert not re.search(r"^  schedule:", wf, re.M), "daily-video.yml: GitHub schedule вернулся (слоты = cron Hermes)"
    assert re.search(r"^  workflow_dispatch:\n    inputs:\n      scheduled:", wf, re.M), "нет dispatch-input scheduled"


if __name__ == "__main__":
    test_selfcheck()
    test_ci_jobs_not_on_release()
    test_daily_video_slots_by_hermes_cron()
    print("OK test_ci_no_release_label")
