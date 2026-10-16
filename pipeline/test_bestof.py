#!/usr/bin/env python3
"""Самопроверка best-of-N по CE (t_b4006a6e): выбор минимума, ошибка критика, модель на запрос."""
import importlib.util
import json
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("bestof", Path(__file__).parent / "bestof.py")
bestof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bestof)

spec_m = importlib.util.spec_from_file_location("music", Path(__file__).parent / "03_music.py")
music = importlib.util.module_from_spec(spec_m)
spec_m.loader.exec_module(music)

# ---- best_of: минимум по min-CE из 3 отрывков ----
paths = ["a", "b", "c"]
i, p, ce = bestof.best_of(3, lambda i: paths[i], lambda fs: [[1.0, 9.0], [0.5, 0.4, 0.6], [2.0, 2.1]])
assert (i, p) == (1, "b"), (i, p)  # min(0.4) < min(1.0) и < min(2.0)
assert ce == [[1.0, 9.0], [0.5, 0.4, 0.6], [2.0, 2.1]]

# средний отрывок хуже концов: min ловит брак в середине
i, _, _ = bestof.best_of(2, lambda i: paths[i], lambda fs: [[9.0, 1.0, 9.0], [2.0, 2.0, 2.0]])
assert i == 0, "min по отрывкам должен выбрать трек с хорошей серединой (1.0)"

# критик вернул не все оценки -> ошибка шага (вслепую нельзя)
try:
    bestof.best_of(3, lambda i: paths[i], lambda fs: [[1.0, 1.0, 1.0]])
    raise SystemExit("должен был упасть: 1/3 оценок")
except RuntimeError:
    pass

# ---- generate_track_v15: model уходит в body ----
class _FakeApi:
    def __init__(self): self.bodies = []
    def post(self, path, body):
        if path == "/query_result":
            return {"data": [{"status": 1, "result": '[{"file": "/v1/audio?path=x"}]'}]}
        self.bodies.append(dict(body))
        return {"data": {"task_id": "t1"}}
    def post_file(self, path, body, field, file_path):
        self.bodies.append(dict(body)); return {"data": {"task_id": "t1"}}
    def get(self, path): return b"mp3"

import os
_d = Path(tempfile.mkdtemp())
api = _FakeApi()
music.generate_track_v15("p", 60, 1, _d / "o.mp3", api=api, poll_sec=0, model="acestep-v15-xl-sft")
assert api.bodies[-1].get("model") == "acestep-v15-xl-sft", api.bodies[-1]
api = _FakeApi()
music.generate_track_v15("p", 60, 1, _d / "o.mp3", api=api, poll_sec=0)
assert "model" not in api.bodies[-1], "без ACE15_MODEL прод не должен менять модель"

print("OK: best-of-N по CE + модель на запрос")
