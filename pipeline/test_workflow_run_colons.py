#!/usr/bin/env python3
"""Инцидент 25.10 (startup_failure PR #258): go-yaml (GitHub) строже pyyaml —
однострочный `run: <значение>` со `: ` внутри значения парсится pyyaml локально,
но GitHub отвергает workflow ЦЕЛИКОМ (0 jobs, conclusion=failure, CI-очередь вслепую).
Правило: любой run с ': ' в значении — только блочный (| или >). Регрессия = строка
`run: python3 -c "… tg_send('🚨 merge-police (P10): PR …')"` из инцидента."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WFS = ROOT / ".github/workflows"
# однострочный run:, значение не блочное (|, >, пустое), содержит ": "
BAD = re.compile(r"^\s*run: [^|>\s].*:\s", re.M)


def test_no_colon_space_in_plain_run_values():
    bad = []
    for f in sorted(WFS.glob("*.yml")):
        for m in BAD.finditer(f.read_text()):
            bad.append((f.name, m.group(0).strip()[:100]))
    assert not bad, "GitHub (go-yaml) отвергнет workflow, перевести run в блочный: " + repr(bad)


def test_regression_incident_line():
    incident = ('        run: python3 -c "from common import tg_send; '
                'tg_send(\'🚨 merge-police (P10): PR смержен раньше зелёного test '
                '— master получил непроверенный коммит. Лог: ${{ github.server_url }}'
                '/=${{ github.repository }}/actions/runs/${{ github.run_id }})\'"')
    assert BAD.search(incident), "регрессия: строка инцидента 25.10 не ловится"


if __name__ == "__main__":  # t_110fa85f: CI запускает файл как скрипт
    _fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for _f in _fns:
        _f()
        print("ok", _f.__name__)
    print(f"PASS {len(_fns)} tests")
