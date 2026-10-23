#!/usr/bin/env python3
"""P18 (аудит 21.10): daily-video 21.10 шёл > 2 ч (03 music до 171 мин), раннер занят зависшим прогоном,
алерт приходит только по job-таймауту 240 мин (а при job-таймауте шаг TG alert может не выполниться).
Инвариант: каждый рабочий шаг выпуска (01 idea .. 07 shorts) имеет свой timeout-minutes <= 60,
таймаут шага = failure() -> TG alert срабатывает (job-таймаут = cancelled, failure()-шаги не идут).
Замер шагов (100 прогонов daily-video): 02 cover max 20.9, 05 publish 28.9, ACE-Step up 10.2 (+ 18-мин health-цикл),
03c 5.2, 07 shorts 5.1, 01 idea 5.3; 03 music из банка 0.1 (генерация в слоте удалена, t_ba72c7aa).
Запуск: python3 pipeline/test_workflow_timeouts.py"""
import re
from pathlib import Path

WF = (Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")
WORK = ("01 idea", "02 cover", "03b animate", "ACE-Step up", "03 music", "03c quality gate", "03d anti-repeat",
        "04 assemble", "04b quality gate final", "05 publish", "05b anti-repeat", "07 shorts")
STEP_MAX = 60


def step_timeouts(wf=WF):
    out = {}
    for blk in re.split(r"\n      - (?=name:|uses:)", wf)[1:]:
        m = re.match(r"name: (.+)", blk)
        if not m:
            continue
        t = re.search(r"^        timeout-minutes: (\d+)", blk, re.M)
        out[m.group(1).strip()] = int(t.group(1)) if t else None
    return out


def test_every_work_step_has_timeout():
    st = step_timeouts()
    for w in WORK:
        names = [n for n in st if n.startswith(w)]
        assert names, f"шаг не найден: {w}"
        for n in names:
            assert st[n] is not None, f"P18: шаг {n!r} без timeout-minutes — зависание держит раннер до 240 мин"
            assert st[n] <= STEP_MAX, f"P18: шаг {n!r} timeout {st[n]} > {STEP_MAX} мин"


def test_alert_on_failure_exists():
    assert re.search(r"- name: TG alert on failure.*?\n        if: failure\(\)", WF, re.S), "нет TG alert на failure()"


if __name__ == "__main__":
    test_every_work_step_has_timeout()
    test_alert_on_failure_exists()
    print("ok")
