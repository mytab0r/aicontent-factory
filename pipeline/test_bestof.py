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

from quality_gate import MIN_CE

assert bestof.MIN_CE is MIN_CE, "порог CE — единый источник: quality_gate.MIN_CE"
gen = lambda k: f"c{k}"
quiet = lambda *a: None

# ---- реальные CE прогона 38971884880 (8 кандидатов XL-sft): побеждает МАКСИМУМ ----
real = [[7.10, 7.2, 7.3], [6.85] * 3, [7.01] * 3, [6.24] * 3, [6.66] * 3, [6.95] * 3, [6.216] * 3, [6.87] * 3]
k, p, rows = bestof.best_of(8, gen, lambda fs: real, log=quiet)
assert (k, p) == (0, "c0"), (k, p)  # 7.10 > всех; старый min() выбрал бы #7 (6.216 < MIN_CE)
assert [r["fail"] != [] for r in rows] == [False, False, False, True, False, False, True, False]

# реф ~7.5 против брака ~3: брак не выигрывает никогда
k, _, _ = bestof.best_of(2, gen, lambda fs: [[3.0, 3.1, 2.9], [7.5, 7.6, 7.4]], log=quiet)
assert k == 1

# min по отрывкам: брак в середине (2.0) топит трек с высокими краями
k, _, _ = bestof.best_of(2, gen, lambda fs: [[9.0, 2.0, 9.0], [7.0, 7.0, 7.0]], log=quiet)
assert k == 1

# CE высокий, но objective (LRA/полосы) FAIL -> не кандидат
k, _, _ = bestof.best_of(2, gen, lambda fs: [[7.9] * 3, [7.0] * 3],
                         objective=lambda p: ["LRA 1.4 < 5.0"] if p == "c0" else [], log=quiet)
assert k == 1

# 0 прошли в раунде 1 -> перегенерация, раунд 2 даёт победителя (номер сквозной)
calls = []
def sc(fs):
    calls.append(list(fs))
    return [[3.0] * 3, [3.2] * 3] if len(calls) == 1 else [[6.9] * 3, [7.3] * 3]
k, p, rows = bestof.best_of(2, gen, sc, log=quiet)
assert (k, p, len(calls), len(rows)) == (3, "c3", 2, 4), (k, p, calls)

# 0 прошли за 3 раунда -> ошибка шага (алерт), а не публикация брака
calls.clear()
try:
    bestof.best_of(2, gen, lambda fs: calls.append(1) or [[3.0] * 3] * 2, log=quiet)
    raise SystemExit("должен был упасть: 0 прошли")
except RuntimeError as e:
    assert "0 кандидатов" in str(e) and len(calls) == 3

# критик вернул не все оценки -> ошибка шага (вслепую нельзя)
try:
    bestof.best_of(3, gen, lambda fs: [[7.0] * 3], log=quiet)
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
assert "lora_name_or_path" not in api.bodies[-1], "в /release_task поля LoRA нет — только /v1/lora/load"
api = _FakeApi()
music.generate_track_v15("p", 60, 1, _d / "o.mp3", api=api, poll_sec=0)
assert "model" not in api.bodies[-1], "без ACE15_MODEL прод не должен менять модель"

# сервер молча подменил модель на primary -> ошибка, а не «XL» в отчёте
class _SwapApi(_FakeApi):
    def post(self, path, body):
        if path == "/query_result":
            return {"data": [{"status": 1, "result": '[{"file": "x", "dit_model": "acestep-v15-turbo"}]'}]}
        return super().post(path, body)
try:
    music.generate_track_v15("p", 60, 1, _d / "o.mp3", api=_SwapApi(), poll_sec=0, model="acestep-v15-xl-sft")
    raise SystemExit("должен был упасть: модель подменена")
except RuntimeError as e:
    assert "turbo" in str(e)

# ---- ace15_prepare: init модели + LoRA с проверкой статуса ----
class _PrepApi:
    def __init__(self, loaded=True): self.calls, self.loaded = [], loaded
    def post(self, path, body, timeout=600):
        self.calls.append((path, body))
        if path == "/v1/init":
            return {"code": 200, "data": {"loaded_model": body["model"]}}
        return {"code": 200, "data": {"message": "ok"}}
    def get(self, path):
        return json.dumps({"data": {"lora_loaded": self.loaded, "use_lora": self.loaded}}).encode()
a = _PrepApi()
st = music.ace15_prepare("acestep-v15-xl-sft", "/app/output/lora/out/final", api=a)
assert [c[0] for c in a.calls] == ["/v1/init", "/v1/lora/load"] and st["lora_loaded"]
assert a.calls[1][1] == {"lora_path": "/app/output/lora/out/final"}
try:
    music.ace15_prepare("acestep-v15-xl-sft", "/bad", api=_PrepApi(loaded=False))
    raise SystemExit("должен был упасть: LoRA не встала")
except RuntimeError:
    pass
a = _PrepApi()
assert music.ace15_prepare(None, None, api=a) == {} and a.calls == [], "прод без env: ни init, ни LoRA"

print("OK: best-of-N по CE + модель на запрос")
