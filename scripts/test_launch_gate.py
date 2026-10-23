#!/usr/bin/env python3
"""Self-check launch_gate: stale GO report => NO-GO regardless of mtime/git; fresh GO => GO."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from launch_gate import gate, REQUIRED

def report(date, verdict):
    body = "\n".join(f"## {s}\nx" for s in REQUIRED)
    return (f"Дата гейта: {date}\n" if date else "") + body + f"\nВЕРДИКТ: {verdict}\n"

def run(text):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(text)
    try:
        return gate(f.name)  # mtime = сейчас: свежий файл не должен спасать старую дату
    finally:
        os.unlink(f.name)

today = time.strftime("%Y-%m-%d", time.gmtime())
old = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 5 * 86400))
assert run(report(today, "GO")) == "GO", run(report(today, "GO"))
assert run(report(old, "GO")).startswith("NO-GO: отчёт старше"), run(report(old, "GO"))
assert run(report(None, "GO")).startswith("NO-GO: нет строки"), run(report(None, "GO"))
assert run(report(today, "NO-GO")).startswith("NO-GO: последний"), run(report(today, "NO-GO"))
print("test_launch_gate OK")
