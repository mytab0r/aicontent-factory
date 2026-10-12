#!/usr/bin/env python3
"""Шаг 1: через 9router (LLM) сгенерировать идею трека + метаданные YouTube."""
import json
import os
import sys
from pathlib import Path

import dd_channel
from common import STATE_DIR, rotate, router_post, next_mood, new_run_dir

# ponytail: фолбэк по списку; квота gemini кончается -> следующая модель
MODELS = ["gemini/gemini-3.8-flash", "auto-worker-combo", "cx/gpt-5.5"]

# Детерминированный фолбэк, если все LLM недоступны: сцены ротируются через
# .state/fallback_idx.txt, чтобы заголовки не повторялись (anti-template).
# ponytail: 8 сцен; расширять списком, если фолбэк станет частым.
SCENES = [
    ("Rainy Tokyo Nights", "🌧️", "rainy Tokyo street at night, neon reflections, anime girl at window"),
    ("Late Night Train", "🚃", "empty anime night train, city lights passing, warm interior glow"),
    ("Cozy Bedroom Study", "📚", "anime girl studying at desk, lamp light, cat sleeping, night window"),
    ("Sunset Rooftop", "🌇", "anime rooftop at sunset, city skyline, soft orange clouds"),
    ("Snowy Café Window", "☕", "small anime café in snow, warm window light, steam from cup"),
    ("Summer Countryside", "🌾", "anime countryside road in summer, cicadas, blue sky, power lines"),
    ("Midnight Convenience Store", "🏪", "anime convenience store at midnight, glowing sign, quiet street"),
    ("Autumn Library", "🍂", "anime library with tall windows, autumn leaves outside, golden light"),
]
USES = ["Study and Relax to", "Sleep and Chill to", "Focus and Work to", "Read and Unwind to"]
TAGS = ["lofi", "anime lofi", "lofi hip hop", "study music", "chill beats", "relaxing music",
        "focus music", "sleep music", "lofi beats", "chillhop", "japanese lofi"]


def fallback_idea(mood: str, state_dir: Path | None = None) -> dict:
    i = rotate("fallback", len(SCENES) * len(USES), state_dir)
    name, emoji, scene = SCENES[i % len(SCENES)]
    use = USES[(i // len(SCENES)) % len(USES)]
    return {
        "mood": mood,
        "cover_prompt": f"{scene}, aesthetic lofi album art, soft pastel colors, no text",
        "title": f"{name} {emoji} Lofi Beats to {use}"[:70],
        "description": f"{name.lower().capitalize()} — {mood} beats to {use.lower()}. "
                       "Calm instrumental music for long study, work and sleep sessions.",
        "tags": TAGS,
        "fallback": True,
    }


def main() -> None:
    channel = os.environ.get("CHANNEL", "lofi")
    if channel == "dd":
        # D&D ambience канал-эксперимент (DECISIONS.md п.8): своя ротация сцен
        # и своя заголовочная формула, состояние отдельно от lofi-ротации.
        scene = dd_channel.next_scene(STATE_DIR / "dd_scene_idx.txt")
        prompt = dd_channel.idea_prompt(scene)
    else:
        mood = os.environ.get("GENRE") or next_mood()
        scene = None
        prompt = f"""Ты продюсер lo-fi/ambient YouTube-канала. Настроение трека: "{mood}".
Верни СТРОГО JSON (без markdown, без пояснений) с полями:
  mood: строка (кратко, как дано)
  cover_prompt: промпт для генерации обложки (на английском, стиль aesthetic lofi album art, без текста на картинке)
  title: заголовок до 70 символов, английский, по формуле топ-каналов ниши
    (DECISIONS.md п.5): "[Сцена/жанр] + emoji + [use-case] Music to Study/
    Relax/Sleep/Focus to" — например "Rainy Tokyo Nights 🌧️ Lofi Beats to
    Study and Relax to". Без фейковых чисел длительности в заголовке.
  description: 2-3 предложения описания видео на английском для YouTube
  tags: список из 8-12 тегов (английские, через запятую в массиве JSON)
"""
    resp, err = None, None
    for model in MODELS:
        try:
            resp = router_post("/chat/completions", {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1500,
                "stream": False,
            })
            break
        except RuntimeError as e:
            print(f"model {model} failed: {e}"[:300])
            err = e
    idea = None
    if resp is not None:
        content = resp["choices"][0]["message"]["content"].strip()
        # LLM иногда оборачивает в ```json ... ``` — срезаем
        if content.startswith("```"):
            content = content.strip("`")
            content = content.split("\n", 1)[1] if "\n" in content else content
            if content.lower().startswith("json"):
                content = content[4:]
        try:
            idea = json.loads(content)
        except json.JSONDecodeError as e:
            err = e
    if idea is None:
        if channel == "dd":
            raise err  # ponytail: D&D-эксперимент без шаблонного фолбэка (ручной запуск)
        print(f"LLM недоступен ({err}); детерминированный фолбэк"[:300])
        idea = fallback_idea(mood, STATE_DIR)
    if channel == "dd":
        idea["channel"] = "dd"
        idea["scene"] = scene["name"] if scene else None

    run_dir = new_run_dir()
    out_path = run_dir / "idea.json"
    out_path.write_text(json.dumps(idea, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"idea -> {out_path}")
    print(json.dumps(idea, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
