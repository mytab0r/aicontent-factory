#!/usr/bin/env python3
"""t_1f53095a R3: запас банка. Цель >= 2 выпуска (40 сегм.); < 1 выпуска (20) = генератор в приоритет
(немедленный dispatch bank-fill) + строка в часовой отчёт; пусто = пропуск слота (bank_release exit 2).
Лимит банка 15 ГБ + пол C: из disk_gate.sh — генератор останавливается до записи (fill и take)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bank  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
Q = lambda *_: None  # noqa: E731


def test_levels():
    assert bank.RELEASE_SEG == 20 and bank.TARGET_RELEASES == 2
    assert bank.reserve_level(45) == "ok"
    assert bank.reserve_level(40) == "ok"
    assert bank.reserve_level(30) == "below_target"
    assert bank.reserve_level(19) == "low"
    assert bank.reserve_level(4) == "empty"   # < MIN_SEG: выпуск пропустит слот
    assert bank.reserve_level(0) == "empty"


def test_status_line_russian_with_numbers():
    s = bank.status_line("anime lofi", 12)
    assert "anime lofi" in s and "12" in s and "0.6" in s and "приоритет" in s, s
    assert "приоритет" not in bank.status_line("anime lofi", 41)


def test_guard_limit_and_disk_gate():
    lim = bank.BANK_LIMIT_KB
    assert lim == 15 * 1048576
    assert bank.guard_reason(lim - 1, 0) is None
    r = bank.guard_reason(lim, 0)
    assert r and "15" in r, r
    r = bank.guard_reason(10, 1)
    assert r and "C:" in r, r


def test_fill_stops_on_guard():
    made = []
    n = bank.fill(5, lambda: 0, lambda i: made.append(i) or "x", lambda p: True, lambda: False,
                  log=Q, guard=lambda: "лимит")
    assert n == 0 and made == [], (n, made)
    calls = iter([None, None, "лимит"])
    n = bank.fill(5, lambda: 0, lambda i: "x", lambda p: True, lambda: False, log=Q,
                  guard=lambda: next(calls))
    assert n == 2, n


def test_disk_gate_uses_single_script():
    import inspect
    src = inspect.getsource(bank.disk_gate_rc)
    assert "disk_gate.sh" in src and '"c"' in src, src


def test_reserve_check_alerts_and_raises_priority_only_when_low():
    sent, disp = [], []
    lines = bank.reserve_check({"anime lofi": 10, "chill phonk": 41}, send=sent.append,
                               dispatch=lambda: disp.append(1))
    assert len(lines) == 2 and disp == [1] and len(sent) == 1 and "anime lofi" in sent[0], (lines, sent)
    sent.clear(); disp.clear()
    bank.reserve_check({"anime lofi": 25, "chill phonk": 41}, send=sent.append, dispatch=lambda: disp.append(1))
    assert sent == [] and disp == []


def test_hourly_workflow():
    wf = (ROOT / ".github/workflows/bank-reserve.yml").read_text(encoding="utf-8")
    assert '"7 * * * *"' in wf, "часовой отчёт"
    assert "bank.py --reserve" in wf
    assert "actions: write" in wf, "dispatch bank-fill = подъём приоритета"
    assert "[self-hosted, pc]" not in wf, "pc-раннер занят fill — отчёт встал бы в очередь за ним"
    fill = (ROOT / ".github/workflows/bank-fill.yml").read_text(encoding="utf-8")
    assert 'BANK_TARGET: "40"' in fill


def test_main_wires_guard():
    import inspect
    src = inspect.getsource(bank.main)
    assert "guard=" in src and "guard_reason(" in src


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
    print("ok test_bank_reserve")
