#!/usr/bin/env python3
"""Шаг 1: через 9router (LLM) сгенерировать идею трека + метаданные YouTube."""
import json
import os
import sys

import dd_channel
from common import router_post, next_mood, new_run_dir

MODEL = "gemini/gemini-3.8-flash"


def main() -> None:
    channel = os.environ.get("CHANNEL", "lofi")
    if channel == "dd":
        # D&D ambience канал-эксперимент (DECISIONS.md п.8): своя ротация сцен
        # и своя заголовочная формула, состояние отдельно от lofi-ротации.
        from common import STATE_DIR

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
    resp = router_post("/chat/completions", {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1500,
        "stream": False,
    })
    content = resp["choices"][0]["message"]["content"].strip()
    # LLM иногда оборачивает в ```json ... ``` — срезаем
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        if content.lower().startswith("json"):
            content = content[4:]
    idea = json.loads(content)
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
