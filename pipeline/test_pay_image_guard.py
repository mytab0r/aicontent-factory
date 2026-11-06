#!/usr/bin/env python3
"""t_88af3bec: stale guard pay-image пропускает сборку, только если после head_sha менялись входы образа.
Тест падает, если Dockerfile копирует путь, не покрытый IMAGE_INPUTS (иначе устаревший образ уйдёт в :latest),
или если guard снова сравнивает точный sha (fresh-сборка недостижима из-за [skip ci]-коммитов бота).
Запуск: python3 pipeline/test_pay_image_guard.py"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = (ROOT / ".github/workflows/pay-image.yml").read_text(encoding="utf-8")
DF = (ROOT / "deploy/pay-page/Dockerfile").read_text(encoding="utf-8")


def test_inputs_cover_dockerfile_copy():
    m = re.search(r'IMAGE_INPUTS: "([^"]+)"', WF)
    assert m, "pay-image.yml: нет IMAGE_INPUTS в stale guard"
    pre = tuple(m.group(1).split())
    srcs = [l.split()[1] for l in DF.splitlines() if l.startswith(("COPY ", "ADD "))]
    assert srcs, "Dockerfile без COPY — тест устарел"
    miss = [s for s in srcs if not (s.rstrip("/") + "/").startswith(pre) and not s.startswith(pre)]
    assert not miss, f"Dockerfile копирует пути вне IMAGE_INPUTS: {miss}"


def test_guard_gates_build_steps():
    assert "compare/$SHA...$BRANCH" in WF, "guard должен сравнивать содержимое, не точный sha"
    for step in ("syntax gate", "build + push"):
        blk = WF.split(step, 1)[1][:200]
        assert "steps.fresh.outputs.ok == 'true'" in blk, f"{step} не закрыт guard"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")
