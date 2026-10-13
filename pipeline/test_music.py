#!/usr/bin/env python3
"""Самопроверка 03_music.py.

История: тест требовал >=6 жанров в прод-ротации (п.5 DECISIONS.md, эпоха
9-жанровой ротации). Владелец отклонил: непрослушанные жанры не входят в прод
(нарушение правила "сначала семпл на A/B"), ротация откачена к единственному
одобренному "anime lofi". Актуальное поведение фиксируем здесь:

- GENRE_PROMPTS = только явно одобренные владельцем жанры (сейчас 1);
  разнообразие ниш живёт в config/dd_scenes.yaml (DD-канал, test_dd_channel.py)
  и CANDIDATE_GENRE_PROMPTS (ждут A/B), не в проде.
- genre_for_mood детерминирован.
- chunk_plan корректен для long-form (1ч+).
"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("music", Path(__file__).parent / "03_music.py")
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)

# ---- прод-ротация: только одобренные жанры ----
assert len(music.GENRE_PROMPTS) >= 1, "прод без жанров"
assert "anime lofi" in music.GENRE_PROMPTS, "одобренный жанр не на месте"
assert all("no vocals" in p or "instrumental" in p for p in music.GENRE_PROMPTS.values())

# жанры-кандидаты не должны утечь в прод до A/B одобрения
approved = set(music.GENRE_PROMPTS)
candidates = set(getattr(music, "CANDIDATE_GENRE_PROMPTS", {}))
assert not (approved & candidates), "жанр не может быть одновременно продом и кандидатом"

# genre_for_mood детерминирован
name1, _ = music.genre_for_mood("rainy night study")
name2, _ = music.genre_for_mood("rainy night study")
assert name1 == name2, "выбор жанра должен быть воспроизводим по сиду"
assert name1 in approved

# ---- длинный формат: конкатенация кусков под sleep/focus (1ч+) ----
assert hasattr(music, "chunk_plan"), "нужна функция, разбивающая long-form на куски API-вызовов"
chunks = music.chunk_plan(total_sec=3600, max_chunk_sec=240)
assert sum(chunks) == 3600
assert all(c <= 240 for c in chunks)
assert len(chunks) == 15  # 3600 / 240

short_chunks = music.chunk_plan(total_sec=60, max_chunk_sec=240)
assert short_chunks == [60], "короткий трек (сигнатурный ролик) не должен дробиться"

print("OK: прод-ротация = одобренные жанры, chunk_plan() корректен для long-form")

# Владелец 12.10: "шипение и просто мрак". Шум в промпте запрещён, тональности 1.5 только мажор.
NOISE = ("vinyl", "hiss", "crackle", "tape", "noise", "dusty")
for name, p in music.GENRE_PROMPTS.items():
    assert not any(w in p.lower() for w in NOISE), f"шум в прод-промпте {name}"
assert all("major" in k for k in music.ACE15_KEYS), "минорные тональности в ACE15_KEYS"


# Эталон владельца 13.10: ref1 = стиль по reference_audio (K/DA Seraphine),
# одобрен: "больше всего заходит по басу, лёгкости, звону, чёткости мелодии".
class _FakeApi:
    def __init__(self): self.calls = []
    def post(self, path, body):
        self.calls.append(("json", path, dict(body)))
        if path == "/query_result":
            return {"data": [{"status": 1, "result": '[{"file": "/v1/audio?path=x"}]'}]}
        return {"data": {"task_id": "t1"}}
    def post_file(self, path, body, field, file_path):
        self.calls.append(("file", path, dict(body), field, str(file_path)))
        return {"data": {"task_id": "t1"}}
    def get(self, path): return b"mp3"

import tempfile, os as _os
_d = Path(tempfile.mkdtemp())
_ref = _d / "ref.wav"; _ref.write_bytes(b"RIFF")
_api = _FakeApi()
music.generate_track_v15("p", 600, 7, _d / "o.mp3", api=_api, poll_sec=0, ref_audio=_ref)
assert _api.calls[0][0] == "file" and _api.calls[0][3] == "reference_audio", _api.calls[0]
assert _api.calls[0][4] == str(_ref)
_api = _FakeApi()
music.generate_track_v15("p", 600, 7, _d / "o.mp3", api=_api, poll_sec=0, ref_audio=_d / "missing.wav")
assert _api.calls[0][0] == "json", "нет файла эталона -> генерация без него, выпуск не падает"
assert "lush synth pads" in music.GENRE_PROMPTS["anime lofi"], "прод-промпт = одобренный ref1"
print("ok ref-style")
