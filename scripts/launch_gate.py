#!/usr/bin/env python3
"""Launch gate: GO only if /opt/data/reports/products/<product>.launch.md has every required section,
was updated within MAX_AGE_H, and ends with a critic line 'ВЕРДИКТ: GO'. Usage: launch_gate.py <product>"""
import os, re, subprocess, sys, time
from pathlib import Path

REQUIRED = ["Счётчик открытий", "Премортем", "Симуляция", "Сухой прогон", "Критик"]
MAX_AGE_H = 72  # ponytail: re-gate every 3 days (owner rule: day-3 repeat goes through the gate too)

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
    return "GO"

if __name__ == "__main__":
    if len(sys.argv) != 2 or not re.fullmatch(r"[a-z0-9-]+", sys.argv[1]):
        sys.exit("usage: launch_gate.py <product-slug>")
    v = gate(str(Path(__file__).resolve().parent.parent / "reports" / "products" / f"{sys.argv[1]}.launch.md"))
    print(v)
    sys.exit(0 if v == "GO" else 1)
