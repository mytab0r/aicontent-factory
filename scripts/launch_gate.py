#!/usr/bin/env python3
"""Launch gate: GO only if reports/products/<product>.launch.md has every required section,
was updated within MAX_AGE_H, and its final critic section carries an authentic subagent
verdict 'ВЕРДИКТ: GO'. Authenticity (t_f807dc99 round-1 review): the final '### Критик'
section must cite its delegation transcript(s) ('transcript:' + deleg_<id>); every cited
deleg_<id>/task-*.log must exist in /opt/data/cache/delegation/live and its last
'ВЕРДИКТ:' line must match the verdict in the report. A verdict typed into the report by
the executor itself no longer passes. Usage: launch_gate.py <product>"""
import os, re, subprocess, sys, time
from pathlib import Path

REQUIRED = ["Счётчик открытий", "Премортем", "Симуляция", "Сухой прогон", "Критик"]
MAX_AGE_H = 72  # ponytail: re-gate every 3 days (owner rule: day-3 repeat goes through the gate too)
LIVE = Path("/opt/data/cache/delegation/live")

def gate(path):
    if not os.path.isfile(path):
        return f"NO-GO: нет отчёта {path}"
    text = open(path, encoding="utf-8").read()
    missing = [s for s in REQUIRED if not re.search(r"^#+ .*" + s, text, re.M)]
    if missing:
        return f"NO-GO: нет разделов {missing}"
    ts = subprocess.run(["git", "log", "-1", "--format=%ct", "--", os.path.basename(path)], cwd=os.path.dirname(path),
                        capture_output=True, text=True).stdout.strip()  # CI checkout сбрасывает mtime
    age_h = (time.time() - (int(ts) if ts else os.path.getmtime(path))) / 3600
    if age_h > MAX_AGE_H:
        return f"NO-GO: отчёт старше {MAX_AGE_H} ч ({age_h:.0f} ч) — повторить гейт"
    verdicts = re.findall(r"ВЕРДИКТ:\s*(GO|NO-GO)", text)
    if not verdicts or verdicts[-1] != "GO":
        return f"NO-GO: последний вердикт критика {verdicts[-1] if verdicts else 'отсутствует'}"
    # t_f807dc99: вердикт обязан происходить из транскрипта субагента-критика (t_26101239: проверяются
    # ВСЕ ссылки deleg_<id> в последней секции критика; каждая должна существовать и совпадать вердиктом).
    heads = re.findall(r"^#+ [^\n]*Критик[^\n]*$", text, re.M)
    if not heads:
        return "NO-GO: нет секции Критик"
    last = text[text.rfind(heads[-1]):]
    if "transcript:" not in last:
        return "NO-GO: нет метки transcript: — вердикт не привязан к транскрипту субагента"
    refs = sorted(set(re.findall(r"deleg_[0-9a-f]{8}", last)))
    if not refs:
        return "NO-GO: вердикт не привязан к транскрипту (нет deleg_<id>) — происхождение не доказано"
    for did in refs:
        log = next(LIVE.glob(f"{did}/task-*.log"), None)
        if log is None:
            return f"NO-GO: транскрипт {did} не найден — происхождение вердикта не доказано"
        v = re.findall(r"ВЕРДИКТ:\s*(GO|NO-GO)", open(log, encoding="utf-8", errors="replace").read()[-20000:])
        if not v:
            return f"NO-GO: в транскрипте {log.name} ({did}) нет строки ВЕРДИКТ"
        if v[-1] != verdicts[-1]:
            return f"NO-GO: вердикт в отчёте ({verdicts[-1]}) != вердикт в транскрипте ({v[-1]}, {did})"
    return "GO"

if __name__ == "__main__":
    if len(sys.argv) != 2 or not re.fullmatch(r"[a-z0-9-]+", sys.argv[1]):
        sys.exit("usage: launch_gate.py <product-slug>")
    v = gate(str(Path(__file__).resolve().parent.parent / "reports" / "products" / f"{sys.argv[1]}.launch.md"))
    print(v)
    sys.exit(0 if v == "GO" else 1)
