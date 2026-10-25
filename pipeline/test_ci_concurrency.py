#!/usr/bin/env python3
"""t_7461c726/t_e7b938b0: вытеснение «higher priority waiting request for ci-<ветка>» допустимо только для
ожидающего прогона ТОЙ ЖЕ ветки; начатый прогон мастера доводится до вердикта. Тест падает, если ключ группы
огрублён (чужие ветки делят группу), возврат cancel-in-progress: true (убийство начатых прогонов, 16 отмен
24.10) или уникальная группа на прогон (неограниченный бэклог очереди), либо push расширен за master. Запуск: python3 pipeline/test_ci_concurrency.py"""
import re
from pathlib import Path

WF = (Path(__file__).resolve().parent.parent / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_group_is_per_branch():
    m = re.search(r"^concurrency:\n  group: (.+)\n", WF, re.M)
    assert m, "ci.yml: нет workflow-level concurrency"
    assert m.group(1).strip() == "ci-${{ github.head_ref || github.ref }}", f"ключ группы изменён: {m.group(1)!r}"
    cip = re.search(r"^  cancel-in-progress: (.+)$", WF, re.M)
    assert cip and cip.group(1).strip() == "false", (
        "cancel-in-progress должен быть false: true убивает начатые прогоны мастера (t_e7b938b0, 16 отмен 24.10); "
        "run_id копит неограниченный бэклог очереди")


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
