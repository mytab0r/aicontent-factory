#!/usr/bin/env python3
"""t_7461c726/t_e7b938b0: отмены «higher priority waiting request for ci-<ветка>» допустимы только как вытеснение
устаревшего коммита ТОЙ ЖЕ PR-ветки. Тест падает, если ключ concurrency огрублён (разные ветки делят группу),
push в master снова делит группу/отменяется (t_e7b938b0: master без вердикта) или push расширен за master. Запуск: python3 pipeline/test_ci_concurrency.py"""
import re
from pathlib import Path

WF = (Path(__file__).resolve().parent.parent / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_group_is_per_branch():
    m = re.search(r"^concurrency:\n  group: (.+)\n", WF, re.M)
    assert m, "ci.yml: нет workflow-level concurrency"
    assert m.group(1).strip() == "ci-${{ github.head_ref || github.run_id }}", (
        f"ключ группы изменён: {m.group(1)!r} — push в master должен иметь уникальную группу (t_e7b938b0)")


def test_master_push_never_cancelled():
    m = re.search(r"^  cancel-in-progress: (.+)$", WF, re.M)
    assert m and m.group(1).strip() == "${{ github.event_name == 'pull_request' }}", (
        "отмена только для PR: на push в master вытеснение теряет вердикт (t_e7b938b0)")


def test_push_only_master():
    m = re.search(r"^on:\n  push:\n    branches: \[(.+?)\]\n  pull_request:", WF, re.M)
    assert m and m.group(1).strip() == "master", "push должен быть только в master, ветки проверяет pull_request"


def test_no_job_level_concurrency():
    assert not re.search(r"^    concurrency:", WF, re.M), "job-level concurrency создаёт доп. группы вытеснения"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")
