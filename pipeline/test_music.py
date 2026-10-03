#!/usr/bin/env python3
"""Самопроверка 03_music.py: жанровая ротация покрывает несколько ниш,
не только lofi (TASK: comment-aware/competitor analysis, docs/DECISIONS.md п.5)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("music", Path(__file__).parent / "03_music.py")
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)

# ---- жанровая ротация шире lofi-зонтика ----
NICHE_KEYWORDS = ["lofi", "ambient", "nature", "meditation", "piano", "sleep", "healing"]
assert len(music.GENRE_PROMPTS) >= 6, "ротация должна покрывать несколько ниш, не одну-две"
all_prompts = " ".join(music.GENRE_PROMPTS.values()).lower()
hit = sum(1 for kw in NICHE_KEYWORDS if kw in all_prompts)
assert hit >= 4, f"промпты не выходят за пределы lofi-зонтика (нашли {hit}/7 ключевых ниш)"

# genre_for_mood остаётся детерминированным
name1, _ = music.genre_for_mood("rainy night study")
name2, _ = music.genre_for_mood("rainy night study")
assert name1 == name2, "выбор жанра должен быть воспроизводим по сиду"

# ---- длинный формат: конкатенация кусков под sleep/focus (1ч+) ----
assert hasattr(music, "chunk_plan"), "нужна функция, разбивающая long-form на куски API-вызовов"
chunks = music.chunk_plan(total_sec=3600, max_chunk_sec=240)
assert sum(chunks) == 3600
assert all(c <= 240 for c in chunks)
assert len(chunks) == 15  # 3600 / 240

short_chunks = music.chunk_plan(total_sec=60, max_chunk_sec=240)
assert short_chunks == [60], "короткий трек (сигнатурный ролик) не должен дробиться"

print("OK: жанровая ротация покрывает несколько ниш, chunk_plan() корректен для long-form")
