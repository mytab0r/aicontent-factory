#!/usr/bin/env python3
"""Шаг 1: через 9router (LLM) сгенерировать идею трека + метаданные YouTube."""
import json
import os
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

import dd_channel
from common import STATE_DIR, rotate, router_post, next_mood, new_run_dir, model_alive
from watchdog import GENRE_IN_TITLE

# ponytail: фолбэк по списку; квота gemini кончается -> следующая модель.
# t_b87507e0 (30.10): glm без кредов (404) и cx/gpt-5.5 (400 unsupported) мертвы на 9router —
# убраны из цепочки; auto-cheap-combo добавлен живым вторым фолбэком (проверено прямым запросом).
# t_b87507e0 rev2 (04.11): gemini/"No active credentials" (404) в runs 41912902493/41751674923 —
# убрана: каждый прогон платил +30 с probe за заведомо мёртвую модель.
MODELS = ["auto-worker-combo", "auto-cheap-combo"]

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
    "anime lofi": "\"[Сезонная сцена] + emoji + [use-case] Music to Study/\n    Relax/Sleep/Focus to\" — например \"Rainy Night Café ☕ Lofi Beats to\n    Study and Relax to\". Сцена конкретная, не общее \"Anime Nights\". Без фейковых чисел длительности.",
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


# M5 (аудит 18.10): сезонная метка вне сезона (🎃/Halloween в ноябре) = устаревший, шаблонный вид.
# Маркер -> месяцы, когда он уместен; вне их маркер вырезается из title детерминированно (после LLM).
SEASON_MARKERS = {"🎃": {9, 10}, "halloween": {10}, "spooky": {10}, "🎄": {11, 12}, "christmas": {11, 12},
                  "xmas": {11, 12}, "🌸": {3, 4, 5}, "sakura": {3, 4, 5}}


def strip_off_season(title: str, today: date) -> str:
    for mark, months in SEASON_MARKERS.items():
        if today.month not in months:
            title = re.sub(re.escape(mark) + r"\s*", "", title, flags=re.I)
    return re.sub(r"\s{2,}", " ", title).strip()


# V15 (аудит 23.10): LLM смешал сезоны «Snowy Café Window 🎃 Cozy Halloween» в октябре.
# Группа сезонных слов -> месяцы, когда она уместна; слово вне сезона в title = повтор LLM.
# ponytail: фикс. словарь; расширять при новых жалобах (CLIP по обложке — V13).
SEASON_WORDS = {
    frozenset({11, 12, 1, 2}): r"snow(?:y|fall|flakes?)?|winter|wintry|christmas|xmas|🎄|❄️?|new year",
    frozenset({9, 10, 11}): r"autumn(?:al)?|pumpkins?|halloween|spooky|🎃|🍂",
    frozenset({3, 4, 5}): r"spring|sakura|cherry blossoms?|🌸",
    frozenset({6, 7, 8}): r"summer(?:y|time)?|cicadas?|fireworks?",
}


def season_conflict(title: str, today: date) -> list:
    """Сезонные слова title вне сезона даты (пусто = согласовано)."""
    bad = []
    for months, pat in SEASON_WORDS.items():
        if today.month not in months:
            bad += re.findall(r"(?<!\w)(?:" + pat + r")(?!\w)", title, flags=re.I)
    return bad


def idea_season_conflict(idea: dict, today: date) -> list:
    """V11 (аудит 24.10): сезон во ВСЕХ полях идеи (title/cover_prompt/description/tags), не только в title.
    Слово группы вне сезона (V15) + метка уже прошедшего праздника (SEASON_MARKERS: halloween после 31.10)."""
    text = " ".join([str(idea.get(k, "")) for k in ("title", "cover_prompt", "description")] + list(idea.get("tags") or []))
    bad = season_conflict(text, today)
    for mark, months in SEASON_MARKERS.items():
        if today.month not in months:
            bad += re.findall(r"(?<!\w)" + re.escape(mark) + r"(?!\w)", text, flags=re.I)
    return list(dict.fromkeys(w.lower() for w in bad))


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


# M1 (аудит 18.10): дубли сцен в заголовках long-form — «Cozy Halloween Night Train» x2 (14.10), «Anime Nights» x2
# (12.10), «… Sunset Rooftop» x2 (16.10). Шаблонность = риск inauthentic content (демонетизация канала).
# Сцена = слова до слова жанра/emoji без сезонных/жанровых наполнителей; Jaccard >= 0.5 с заголовком за 14 дней = дубль.
TITLES_FILE, TITLE_DAYS, TITLE_JACCARD = "titles.json", 14, 0.5
FILLER = {"cozy", "autumn", "fall", "anime", "chill", "the", "a", "an", "of", "on", "in", "at", "and", "with"}


def scene_words(title: str) -> set:
    t = re.split(r"[^\w\s'&/.,:-]|\b(?:lo-?fi|phonk|chill|beats|music)\b", title, maxsplit=1, flags=re.I)[0]
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z0-9]+", t)) - FILLER


def dup_title(title: str, recent: list, today: date, days: int = TITLE_DAYS):
    """Заголовок за `days` дней с той же сценой (Jaccard >= TITLE_JACCARD) или None."""
    a = scene_words(title)
    for r in recent:
        b = scene_words(r["title"])
        if a and b and (today - date.fromisoformat(r["date"])).days < days and len(a & b) / len(a | b) >= TITLE_JACCARD:
            return r["title"]
    return None


def recent_titles(state_dir: Path | None = None) -> list:
    f = (state_dir or STATE_DIR) / TITLES_FILE
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def remember_title(title: str, today: date, state_dir: Path | None = None) -> None:
    """ponytail: пишется на шаге 01 (до публикации): несостоявшийся выпуск тоже занимает сцену на 14 дней — лишь больше разнообразия."""
    d = state_dir or STATE_DIR
    d.mkdir(exist_ok=True)
    keep = [r for r in recent_titles(d) if (today - date.fromisoformat(r["date"])).days < 60]
    (d / TITLES_FILE).write_text(json.dumps(keep + [{"date": today.isoformat(), "title": title}], ensure_ascii=False,
                                            indent=1), encoding="utf-8")


def owning_idea() -> None:
    """S1 ch1 «Economics of Owning»: скрипт Short через 9router; невалидный ответ = следующая модель.
    ponytail: без шаблонного фолбэка (inauthentic content) — нет валидного скрипта, нет выпуска."""
    import owning_channel as oc
    plan = oc.next_plan(STATE_DIR)
    prompt, err = oc.idea_prompt(plan), None
    # t_b87507e0 (30.10): glm убран из цепочки — нет активных кредов на 9router (404 model_not_found).
    for model in MODELS:
        if not model_alive(model, router_post):  # t_b87507e0: мёртвая (404/400) / лежащая (5xx) -> следующая
            err = RuntimeError(f"{model}: probe failed (404/400/5xx)")
            continue
        try:
            # 4000: reasoning-модели тратят бюджет до ответа (при 1500 content пустой); json_object чинит битый JSON combo
            resp = router_post("/chat/completions", {"model": model, "stream": False, "max_tokens": 4000,
                                                     "response_format": {"type": "json_object"},
                                                     "messages": [{"role": "user", "content": prompt}]})
            idea = oc.validate_script(oc.parse_json(resp["choices"][0]["message"]["content"]))
            break
        except (RuntimeError, ValueError, KeyError, IndexError, AttributeError) as e:  # content=None → AttributeError
            print(f"model {model}: {e}"[:300])
            err = e
    else:
        raise SystemExit(f"нет валидного скрипта: {err}")
    idea.update(channel="owning", topic=plan["topic"], plan=plan)
    out = new_run_dir() / "idea.json"
    out.write_text(json.dumps(idea, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"idea -> {out}\n{json.dumps(idea, ensure_ascii=False, indent=2)}")


def llm_idea(prompt: str):
    """(idea | None, ошибка): модели по очереди, ```json-обёртка срезается."""
    err = None
    for model in MODELS:
        if not model_alive(model, router_post):  # мёртвая (404/400) / лежащая (5xx) -> следующая
            err = RuntimeError(f"{model}: probe failed (404/400/5xx)")
            continue
        try:
            resp = router_post("/chat/completions", {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1500,
                "stream": False,
            })
            # t_b87507e0 rev2: разбор ответа ВНУТРИ try у каждой модели — content=None
            # (combo отдаёт {"content": null}) раньше вылетал AttributeError мимо fallback.
            content = resp["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError(f"content={content!r}")
            content = content.strip()
            if content.startswith("```"):
                content = content.strip("`")
                content = content.split("\n", 1)[1] if "\n" in content else content
                if content.lower().startswith("json"):
                    content = content[4:]
            return json.loads(content), None
        except (RuntimeError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            print(f"model {model} failed: {e}"[:300])
            err = e
    return None, err


def main() -> None:
    channel = os.environ.get("CHANNEL", "lofi")
    if channel == "owning":
        return owning_idea()
    if channel == "dd":
        # D&D ambience канал-эксперимент (DECISIONS.md п.8): своя ротация сцен
        # и своя заголовочная формула, состояние отдельно от lofi-ротации.
        scene = dd_channel.next_scene(STATE_DIR / "dd_scene_idx.txt")
        prompt = dd_channel.idea_prompt(scene)
    else:
        mood = os.environ.get("GENRE") or next_mood()
        scene = None
        prompt = build_prompt(mood, date.today())
    recent = recent_titles() if channel != "dd" else []
    for attempt in range(3):  # M1: LLM повторил сцену за 14 дней -> повтор с запретом этих сцен
        idea, err = llm_idea(prompt)
        if idea is None or channel == "dd":
            break
        idea["title"] = ensure_genre_word(strip_off_season(idea.get("title", ""), date.today()), mood)
        dup = dup_title(idea["title"], recent, date.today())
        off = idea_season_conflict(idea, date.today())  # V11: все поля, не только title
        if not dup and not off:
            break
        if off:
            print(f"V15 сезон не совпадает: {idea['title']!r} {off}"[:300])
            prompt += f"\nНЕ используй вне сезона: {', '.join(off)}. Только сезон: {season_hint(date.today())}."
            idea = None
            continue
        print(f"M1 дубль сцены: {idea['title']!r} ~ {dup!r} (попытка {attempt + 1})"[:300])
        prompt += f"\nНЕ повторяй сцену из заголовка: {dup}. Выбери другое место/время."
        idea = None
    if idea is None:
        if channel == "dd":
            raise err  # ponytail: D&D-эксперимент без шаблонного фолбэка (ручной запуск)
        print(f"LLM недоступен/повторы ({err}); детерминированный фолбэк"[:300])
        for _ in range(len(SCENES) * len(USES)):
            idea = fallback_idea(mood, STATE_DIR)
            if not dup_title(idea["title"], recent, date.today()) and not idea_season_conflict(idea, date.today()):
                break
    if channel == "dd":
        idea["channel"] = "dd"
        idea["scene"] = scene["name"] if scene else None
    else:
        remember_title(idea["title"], date.today())

    run_dir = new_run_dir()
    out_path = run_dir / "idea.json"
    out_path.write_text(json.dumps(idea, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"idea -> {out_path}")
    print(json.dumps(idea, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
