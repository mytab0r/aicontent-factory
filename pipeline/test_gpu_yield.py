#!/usr/bin/env python3
"""23.10: чужой GPU-контейнер (flint llama-server) занял VRAM, банк 3 прогона подряд без сегментов.
Каждая GPU-работа (bank fill, daily-video) обязана вызвать gpu_yield.sh stop до генерации и restore в конце."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github/workflows"


def problems(text, name):
    bad = []
    if "ACE-Step up" not in text:
        return bad
    up = text.index("name: ACE-Step up")
    stop = text.find("gpu_yield.sh stop")
    if stop < 0 or stop > text.index("\n      - name:", up + 1):
        bad.append(f"{name}: нет gpu_yield.sh stop в шаге ACE-Step up")
    if "gpu_yield.sh restore" not in text:
        bad.append(f"{name}: нет gpu_yield.sh restore")
    return bad


def test_gpu_jobs_evict_foreign_gpu_tenants():
    bad = []
    for n in ("bank-fill.yml", "daily-video.yml"):
        bad += problems((WF / n).read_text(encoding="utf-8"), n)
    assert bad == [], bad


def test_script_spares_ace_step():
    s = (ROOT / "deploy/gpu-pc/gpu_yield.sh").read_text(encoding="utf-8")
    assert '[ "$n" = ace-step ] && continue' in s and "DeviceRequests" in s


def test_check_catches_regression():
    old = "steps:\n      - name: ACE-Step up (x)\n        run: docker start ace-step\n      - name: next\n"
    assert len(problems(old, "old")) == 2


if __name__ == "__main__":
    test_gpu_jobs_evict_foreign_gpu_tenants(); test_script_spares_ace_step(); test_check_catches_regression(); print("ok")
