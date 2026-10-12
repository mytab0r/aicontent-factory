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
- long-form связность: test_music_coherent.py.
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

print("OK: прод-ротация = одобренные жанры (long-form: test_music_coherent.py)")
