#!/usr/bin/env python3
"""t_7461c726: отмены «higher priority waiting request for ci-<ветка>» допустимы только как вытеснение
устаревшего коммита ТОЙ ЖЕ ветки. Тест падает, если ключ concurrency огрублён (разные ветки делят группу)
или push расширен за master (дубль push+PR на один коммит). Запуск: python3 pipeline/test_ci_concurrency.py"""
import re
from pathlib import Path

WF = (Path(__file__).resolve().parent.parent / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_group_is_per_branch():
    m = re.search(r"^concurrency:\n  group: (.+)\n  cancel-in-progress: (\w+)", WF, re.M)
    assert m, "ci.yml: нет workflow-level concurrency"
    assert m.group(1).strip() == "ci-${{ github.head_ref || github.ref }}", f"ключ группы изменён: {m.group(1)!r}"
    assert m.group(2) == "true"


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
