#!/usr/bin/env python3
"""Инцидент 16.10 (t_27db5b44, xl-probe 38977233104/38978766252/38981912196): job salvage-tg на
release-раннере искал sample_A в /tmp/runner/*/xlrun и в docker-томе gh-runner-aicontent-factory-work.
Workdir pc-раннера тогда был tmpfs внутри его контейнера, тома не было: `docker run -v <имя>:` молча
СОЗДАЛ пустой том (ls /w: создан 22:42 = первый прогон salvage) -> "sample_A не найден".
Класс: передача файлов между job'ами через чужую ФС раннера. Каждый раннер = отдельный контейнер,
его workdir/том другому job'у не гарантирован. Файлы между job'ами — только actions/upload/download-artifact
или в пределах одного job'а (фикс 04ad962: exfil шагом самого pc-job).
Правило: монтировать gh-runner-*-work могут только workflow, создающие раннеры."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WFS = ROOT / ".github/workflows"
RUNNER_ADMIN = {"pc-ops.yml", "runner-unbreak.yml"}  # создают контейнеры раннеров
BAD = re.compile(r"-v\s+\"?(gh-runner-[\w.$-]*-work|\$\{?VOL\}?)\"?:")


def scan(name, text):
    return [] if name in RUNNER_ADMIN else [(name, m.group(0)) for m in BAD.finditer(text)]


def test_no_job_reads_foreign_runner_workdir_volume():
    bad = [b for f in sorted(WFS.glob("*.yml")) for b in scan(f.name, f.read_text())]
    assert not bad, ("job читает workdir/том чужого раннера — файлы туда не попадают (t_27db5b44, "
                     "\"sample_A не найден (ни workdir, ни volume pc-раннера)\"); передавать через artifact "
                     "или в том же job'е: " + repr(bad))


def test_regression_incident_line():
    incident = "            docker run --rm -v gh-runner-aicontent-factory-work:/w:ro alpine:3.20 \\\n"
    assert scan("xl-probe.yml", incident), "регрессия: строка salvage-tg из инцидента 16.10 не ловится"


if __name__ == "__main__":  # t_110fa85f: CI запускает файл как скрипт
    _fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for _f in _fns:
        _f()
        print("ok", _f.__name__)
    print(f"PASS {len(_fns)} tests")
