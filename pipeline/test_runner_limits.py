#!/usr/bin/env python3
"""t_8ba1bcfb: лимит acf-раннеров = 4g/4cpu везде. janitor.sh enforce_limits возвращает его после внешнего
`docker update` (28.10: 1G/1CPU -> SIGKILL ffmpeg в job test). Расхождение эталона между janitor и
workflow-ами = янитор будет «чинить» в другую сторону. Запуск: python3 pipeline/test_runner_limits.py"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JAN = (ROOT / "deploy/gpu-pc/janitor.sh").read_text()


def test_janitor_enforces_4g():
    body = JAN.split("enforce_limits() {", 1)[1].split("\n}", 1)[0]
    assert "--memory 4g --memory-swap 4g --cpus 4" in body, body
    assert "-ge 4294967296" in body
    for n in ("gh-runner-acf-release", "gh-runner-aicontent-factory", "gh-runner-acf-ci"):
        assert n in JAN.split("ACF_RUNNERS=", 1)[1].split("\n", 1)[0], n
    loop = JAN.split("while true; do", 1)[1]
    assert loop.lstrip().startswith("enforce_limits"), "enforce_limits не вызывается в цикле"


def test_runner_runs_use_same_limit():
    files = list((ROOT / ".github/workflows").glob("*.yml")) + [ROOT / "deploy/gpu-pc/janitor.sh"]
    seen = 0
    for f in files:
        for cmd in re.findall(r"docker run\b[^\n]*--memory[ =](\S+)", f.read_text()):
            seen += 1
            assert cmd == "4g", f"{f.name}: --memory {cmd} != 4g (эталон enforce_limits)"
    assert seen >= 3, seen


if __name__ == "__main__":
    test_janitor_enforces_4g(); test_runner_runs_use_same_limit(); print("ok")
