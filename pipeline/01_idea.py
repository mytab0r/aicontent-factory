#!/usr/bin/env python3
"""Шаг 1: через 9router (LLM) сгенерировать идею трека + метаданные YouTube."""
import json
import os
import sys
from datetime import date
from pathlib import Path

import dd_channel
from common import STATE_DIR, rotate, router_post, next_mood, new_run_dir
from watchdog import GENRE_IN_TITLE

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
# Теги по жанру (t_c678b8fa шаг 3): первый тег = жанр, остальное — общие нишевые.
GENRE_TAGS = {
    "anime lofi": ["lofi", "anime lofi", "lofi hip hop", "study music", "chill beats", "relaxing music",
                   "focus music", "sleep music", "lofi beats", "chillhop", "japanese lofi"],
    "chill phonk": ["phonk", "chill phonk", "wave phonk", "drift phonk", "phonk music", "night drive",
                    "study music", "focus music", "chill beats", "brazilian phonk", "phonk mix"],
}
TAGS = GENRE_TAGS["anime lofi"]  # legacy-имя (тесты/фолбэк lofi)
USES = ["Study and Relax to", "Sleep and Chill to", "Focus and Work to", "Read and Unwind to"]

# Сезон по месяцу: топ lofi за 30 дн (13.10) = сезонные ролики малых каналов 85k-436k
# просмотров (halloween/autumn). ponytail: фикс. таблица по месяцам, без календаря праздников.
SEASONS = {
    1: "winter, snow, cozy new year", 2: "late winter, snow melting, valentine warmth",
    3: "early spring, first blossoms", 4: "spring, cherry blossom sakura", 5: "late spring, fresh green, gentle rain",
    6: "early summer, rainy season tsuyu", 7: "summer, fireworks festival, cicadas", 8: "summer night, festival lanterns",
    9: "early autumn, golden light", 10: "autumn + cozy halloween (pumpkins, candles, black cat, not scary)",
    11: "late autumn + early christmas (first christmas lights, fireplace, warm tea, falling leaves)", 12: "winter, christmas lights, snow",
}


def season_hint(today: date) -> str:
    return SEASONS[today.month]


# Заголовочная формула по жанру: guard жанра (watchdog.GENRE_IN_TITLE) матчит
# слово жанра в заголовке выпуска — формула обязана его туда принести.
TITLE_FORMULAS = {
    "anime lofi": "\"[Сезонная сцена] + emoji + [use-case] Music to Study/\n    Relax/Sleep/Focus to\" — например \"Pumpkin Café on a Rainy Night 🎃 Lofi Beats to\n    Study and Relax to\". Сцена конкретная, не общее \"Anime Nights\". Без фейковых чисел длительности.",
    "chill phonk": "\"[Сезонная сцена] + emoji + Phonk Beats to [use-case]\" — например\n    \"Neon Highway at Midnight 🌃 Phonk Beats to Drift and Focus to\". Слово Phonk обязательно\n    в заголовке. Сцена конкретная (ночная дорога/неон/город), без \"Lofi\". Без фейковых чисел длительности.",
}


def build_prompt(mood: str, today: date, state_dir: Path | None = None) -> str:
    """LLM-промпт: сезон + ротируемая сцена, чтобы заголовки/обложки не повторялись."""
    name, _, scene = SCENES[rotate("scene", len(SCENES), state_dir)]
    formula = TITLE_FORMULAS.get(mood, TITLE_FORMULAS["anime lofi"])
    return f"""Ты продюсер lo-fi/ambient YouTube-канала. Настроение трека: "{mood}".
Сезон (обязательно отрази в сцене, обложке и заголовке): {season_hint(today)}.
Базовая сцена для вариации: {name} ({scene}).
Верни СТРОГО JSON (без markdown, без пояснений) с полями:
  mood: строка (кратко, как дано)
  cover_prompt: промпт для генерации обложки (на английском, стиль aesthetic lofi album art, без текста на картинке; сезонные детали в сцене)
  title: заголовок до 70 символов, английский, по формуле топ-каналов ниши
    (DECISIONS.md п.5): {formula}
  description: 2-3 предложения описания видео на английском для YouTube
  tags: список из 8-12 тегов (английские, через запятую в массиве JSON), включая сезонный тег
"""


def fallback_idea(mood: str, state_dir: Path | None = None) -> dict:
    i = rotate("fallback", len(SCENES) * len(USES), state_dir)
    name, emoji, scene = SCENES[i % len(SCENES)]
    use = USES[(i // len(SCENES)) % len(USES)]
    genre_word = "Phonk" if "phonk" in mood.lower() else "Lofi"
    return {
        "mood": mood,
        "cover_prompt": f"{scene}, aesthetic lofi album art, soft pastel colors, no text",
        "title": f"{name} {emoji} {genre_word} Beats to {use}"[:70],
        "description": f"{name.lower().capitalize()} — {mood} beats to {use.lower()}. "
                       "Calm instrumental music for long study, work and sleep sessions.",
        "tags": GENRE_TAGS.get(mood, TAGS),
        "fallback": True,
    }


def ensure_genre_word(title: str, mood: str) -> str:
    """Гарантия слова жанра в title: guard дублей (watchdog.already_published)
    ищет маркер жанра в заголовке; если LLM его не принёс — дописываем
    детерминированно («... Phonk Beats»), сохраняя лимит 70 символов."""
    toks = GENRE_IN_TITLE.get((mood or "").lower())
    if not toks or any(t in title.lower() for t in toks):
        return title
    word = toks[0].capitalize()
    for suffix in (f" {word} Beats", f" | {word}", f" [{word}]"):
        if len(title + suffix) <= 70:
            return title + suffix
    # ponytail: обрезка хвоста под маркер; аудиту заголовков — при жалобах guard'а.
    keep = title[: 70 - len(suffix) - 1].rstrip()
    return f"{keep} {suffix.strip()}" if keep else suffix.strip()


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
        prompt = build_prompt(mood, date.today())
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
    else:
        # Пост-проверка слова жанра (t_93ee3737): guard дублей матчит маркер жанра
        # в заголовке; если LLM его пропустил — детерминированно дописываем.
        fixed = ensure_genre_word(idea.get("title", ""), mood)
        if fixed != idea.get("title"):
            print(f"title без слова жанра ({mood}); исправлено: {fixed!r}"[:300])
            idea["title"] = fixed

    run_dir = new_run_dir()
    out_path = run_dir / "idea.json"
    out_path.write_text(json.dumps(idea, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"idea -> {out_path}")
    print(json.dumps(idea, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
