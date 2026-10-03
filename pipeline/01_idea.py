#!/usr/bin/env python3
"""Шаг 1: через 9router (LLM) сгенерировать идею трека + метаданные YouTube."""
import json
import sys

from common import router_post, next_mood, new_run_dir

MODEL = "gemini/gemini-3.8-flash"


def main() -> None:
    mood = next_mood()
    prompt = f"""Ты продюсер lo-fi/ambient YouTube-канала. Настроение трека: "{mood}".
Верни СТРОГО JSON (без markdown, без пояснений) с полями:
  mood: строка (кратко, как дано)
  cover_prompt: промпт для генерации обложки (на английском, стиль aesthetic lofi album art, без текста на картинке)
  title: цепляющий заголовок видео на YouTube (английский, до 70 символов, с указанием "lofi" или "ambient")
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

    run_dir = new_run_dir()
    out_path = run_dir / "idea.json"
    out_path.write_text(json.dumps(idea, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"idea -> {out_path}")
    print(json.dumps(idea, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
