#!/usr/bin/env python3
"""Self-check ch2_snapshot (без сети): формат строк снапшота."""
import importlib.util
import sys
import datetime as dt
from pathlib import Path

spec = importlib.util.spec_from_file_location("ch2s", Path(__file__).parent / "ch2_snapshot.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# traffic_sources: мок api
class FakeAPI:
    def __init__(self, rows):
        self.rows = rows
    def __call__(self, url, at):
        return {"rows": self.rows}

pa_rows = [["RELATED_VIDEO", 10], ["SEARCH", 5]]
m.pa.api = FakeAPI(pa_rows)
ts = m.traffic_sources("at", "vid1", "2026-10-20")
assert ts == {"RELATED_VIDEO": 10, "SEARCH": 5}, ts
assert sorted(ts.items(), key=lambda x: -x[1])[0][0] == "RELATED_VIDEO"

# snapshot: мок collect
def fake_collect(at):
    return [{"id": "v1", "title": "T1", "published": dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc),
             "retention": 33.5, "ctr": (1200, 4.2)}], None
m.pa.collect = fake_collect
m.pa.metric = lambda at, ids, start, name: {"v1": 7.0 if name == "views" else 1.0}
m.traffic_sources = lambda at, vid, start: {"SEARCH": 3}
out = m.snapshot("at")
assert "показы=1200" in out, out
assert "CTR=4.2%" in out, out
assert "удержание=33.5%" in out, out
assert "SEARCH=3" in out, out
assert "просмотры=7" in out and "подписки=1" in out, out

# гейт запуска: в воркфлоу ch2 token/publish выполняются только при GO (без GO — выход без upload)
import re
for wf in ("daily-listshow.yml", "daily-whatif.yml"):
    y = (Path(__file__).parent.parent / ".github" / "workflows" / wf).read_text(encoding="utf-8")
    assert "scripts/launch_gate.py ch2-whatif" in y, wf
    for step in re.split(r"\n      - name: ", y)[1:]:
        if step.startswith(("token", "publish")):
            assert "if: steps.gate.outputs.go == '1'" in step, (wf, step.splitlines()[0])
def fake_empty(at):
    return [], None
m.pa.collect = fake_empty
assert "канал пуст" in m.snapshot("at")
print("ch2_snapshot self-check OK")
