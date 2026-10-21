#!/usr/bin/env python3
"""21.10 run 39576809258: бюджет час-микса 7200 с вмещал 2 сегмента (замер ~28 мин на сегмент
с гейтом 3 кандидата) -> микс 180 с < 900 с, выпуск не состоялся. Бюджет должен вмещать
минимальный выпуск (900 с / 180 с = 5 сегментов) и помещаться в timeout джобы."""
import re
from pathlib import Path

WF = (Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")
SEG_COST_SEC = 28 * 60  # замер 21.10: 3 кандидата + критик
PRE_POST_SEC = 70 * 60  # до music ~30 мин, после (гейт, сборка, публикация, shorts) ~40 мин


def test_mix_budget_fits_min_release_and_job_timeout():
    m = re.search(r'ACE15_MIX_BUDGET_SEC:\s*"?(\d+)', WF)
    budget = int(m.group(1)) if m else 7200  # дефолт 03_music.py
    timeout = int(re.search(r"timeout-minutes:\s*(\d+)", WF).group(1)) * 60
    assert budget >= 5 * SEG_COST_SEC, f"бюджет {budget} с < 5 сегментов x {SEG_COST_SEC} с"
    assert budget + PRE_POST_SEC <= timeout, f"бюджет {budget} + {PRE_POST_SEC} > timeout {timeout}"


def test_refpool_ytdlp_in_venv():
    deps = WF.split("- name: install deps", 1)[1].split("- name:", 1)[0]
    assert "yt-dlp" in deps, "refpool зовёт yt-dlp из .venv — без него эталон дня всегда fallback"


if __name__ == "__main__":
    test_mix_budget_fits_min_release_and_job_timeout()
    test_refpool_ytdlp_in_venv()
    print("ok")
