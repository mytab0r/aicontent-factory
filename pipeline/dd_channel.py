"""D&D ambience канал-эксперимент: профиль, сцены, ротация.

Решение: DECISIONS.md п.8 (white-space ресёрч 2026-10-03 — гипотеза #1,
score 100: спрос "dnd music" Trends 23->75.6, SERP-топ 5 лет старый,
ACE-Step scene-tag fit 5/5). Прод-пайплайн lofi не трогаем: этот модуль
используется 01_idea.py только когда CHANNEL=dd.
"""
import json
from pathlib import Path

SCENES_YAML = Path(__file__).resolve().parent.parent / "config" / "dd_scenes.yaml"

PROFILE = {
    "name": "Tavern & Dungeon Ambience",
    "channel_id_env": "DD_CHANNEL_ID",  # YouTube channelId отдельного канала
    "shorts_per_week": (3, 5),
    "format": "long-form ambience 1h+ + occasional scene shorts",
}


def load_scenes() -> list[dict]:
    """Минимальный YAML-парсер (как load_moods в common.py) для dd_scenes.yaml.
    Формат: список сцен, каждая — вложенный dict с ключами name/music_prompt/
    cover_prompt/title_scene. Структура фиксирована (2 уровня), pyyaml не нужен."""
    scenes: list[dict] = []
    cur: dict | None = None
    last_key: str | None = None
    for raw in SCENES_YAML.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith("- "):
            first = raw[2:].strip()
            # поддержка "- name: cozy tavern" (key: value в первой строке сцены)
            if ":" in first and first.split(":", 1)[0].strip() == "name":
                cur = {"name": first.split(":", 1)[1].strip()}
            else:
                cur = {"name": first}
            scenes.append(cur)
            last_key = None
            continue
        if cur is None:
            continue
        stripped = raw.strip()
        if raw.startswith("  ") and ":" in stripped and not raw.startswith("    "):
            key, _, val = stripped.partition(":")
            cur[key.strip()] = val.strip().strip('"')
            last_key = key.strip()
        elif raw.startswith("    ") and last_key:
            # продолжение предыдущей строки (перенос длинного промпта)
            cur[last_key] = f"{cur[last_key]} {stripped}".strip()
    return scenes


def next_scene(state_file: Path) -> dict:
    """Детерминированная ротация сцен (анти-шаблонная политика: каждая сцена
    уникальна до полного цикла). Состояние — отдельный файл, чтобы не мешать
    lofi-ротации .state/mood_idx.txt."""
    scenes = load_scenes()
    state_file.parent.mkdir(exist_ok=True)
    idx = int(state_file.read_text()) if state_file.exists() else 0
    scene = scenes[idx % len(scenes)]
    state_file.write_text(str(idx + 1))
    return scene


def profile() -> dict:
    return PROFILE


def idea_prompt(scene: dict) -> str:
    """Промпт для 01_idea.py (LLM): сцена + требования формата ниши.
    Заголовочная формула ниши — сцена+атмосфера, не "beats to X to"."""
    return f"""Ты продюсер YouTube-канала оригинальной D&D / fantasy tavern ambience музыки.
Сцена: "{scene['title_scene']}".
Музыка: {scene['music_prompt']}
Верни СТРОГО JSON (без markdown) с полями:
  mood: строка (кратко)
  cover_prompt: промпт обложки (английский, fantasy {scene['title_scene']} painting,
    тёплая атмосферная иллюстрация, без текста на картинке, без персонажей с лицами крупным планом)
  title: заголовок до 70 символов, английский, формат ниши ambience:
    "[Scene] Ambience - [Mood/Activity descriptor]" — например
    "Cozy Tavern Ambience - Warm Fireside Music for D&D Sessions".
    НЕ использовать шаблон "beats to study to".
  description: 2-3 предложения описания на английском (для игроков D&D, мейзмастерам
    на сессию, фон для чтения фэнтези)
  tags: 8-12 тегов (dnd, dungeons and dragons, tavern ambience, fantasy music, ...)
"""


if __name__ == "__main__":
    print(json.dumps(profile(), indent=2))
    for s in load_scenes():
        print(f"- {s['name']}: {s['music_prompt'][:80]}...")
