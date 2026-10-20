#!/usr/bin/env python3
"""01_idea: сезонная тема + ротация сцены в LLM-промпте (LOG 13.10).

Данные: топ lofi за 30 дн (YouTube search, 13.10) - halloween/autumn ролики малых каналов
85k-436k просмотров; наши 3 последних заголовка почти одинаковы ("Anime Nights ...") -
шаблонность = риск inauthentic content. Запуск: python3 pipeline/test_idea_season.py
"""
import importlib.util
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("idea", HERE / "01_idea.py")
idea = importlib.util.module_from_spec(spec)
spec.loader.exec_module(idea)


def test_season_by_month():
    assert "halloween" in idea.season_hint(date(2026, 10, 13)).lower()
    assert "autumn" in idea.season_hint(date(2026, 11, 5)).lower()
    # RESEARCH 14.10: рождественский lofi набирает 2-13k с начала октября -> с ноября сцены с рождеством
    assert "christmas" in idea.season_hint(date(2026, 11, 5)).lower()
    assert "christmas" in idea.season_hint(date(2026, 12, 20)).lower()
    assert "spring" in idea.season_hint(date(2027, 4, 1)).lower()
    for m in range(1, 13):
        assert idea.season_hint(date(2026, m, 1)), m


def test_prompt_has_season_and_rotating_scene():
    with tempfile.TemporaryDirectory() as d:
        p1 = idea.build_prompt("anime lofi", date(2026, 10, 13), Path(d))
        p2 = idea.build_prompt("anime lofi", date(2026, 10, 14), Path(d))
    assert "halloween" in p1.lower()
    assert p1 != p2, "сцена должна ротироваться между выпусками"
    names = [s[0] for s in idea.SCENES]
    assert any(n in p1 for n in names) and any(n in p2 for n in names)


def test_llm_title_without_genre_word_fixed_for_guard():
    """Пост-проверка LLM-пути (t_93ee3737): title без слова жанра чинится
    детерминированно, иначе guard дублей (watchdog.already_published) не увидит
    выпуск и retry-слот опубликует второй ролик жанра за день."""
    import datetime as dt

    from watchdog import already_published

    def rss_with(title):
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
 <entry><yt:videoId>v1</yt:videoId><title>{title}</title><published>2026-10-13T09:00:00+00:00</published></entry>
</feed>'''

    for mood in ("anime lofi", "chill phonk"):
        bad = "Neon Highway at Midnight Beats to Drift and Focus to"
        assert not already_published(rss_with(bad), dt.date(2026, 10, 13), mood)
        fixed = idea.ensure_genre_word(bad, mood)
        assert fixed != bad and len(fixed) <= 70
        assert already_published(rss_with(fixed), dt.date(2026, 10, 13), mood)
    # уже корректный title не меняется
    assert idea.ensure_genre_word("Pumpkin Cafe Lofi Beats to Study to", "anime lofi") \
        == "Pumpkin Cafe Lofi Beats to Study to"
    assert idea.ensure_genre_word("Neon Highway Phonk Beats to Drift to", "chill phonk") \
        == "Neon Highway Phonk Beats to Drift to"


def test_off_season_markers_stripped():
    """M5: 17.10 в заголовках 🎃 ×5; с 1.11 метка Halloween устарела. Регресс: p-kkEmLGviU-подобный title в ноябре."""
    t = "Autumn Café Window 🎃 Halloween Lofi Beats to Relax and Drift"
    nov = idea.strip_off_season(t, date(2026, 11, 1))
    assert "🎃" not in nov and "halloween" not in nov.lower() and "Lofi" in nov, nov
    assert idea.strip_off_season(t, date(2026, 10, 17)) == t
    assert "🎄" not in idea.strip_off_season("Snow Café 🎄 Lofi", date(2027, 1, 10))
    with tempfile.TemporaryDirectory() as d:
        p = idea.build_prompt("anime lofi", date(2026, 11, 2), Path(d))
    assert "🎃" not in p and "halloween" not in p.lower(), "пример формулы не должен тянуть 🎃 вне сезона"




def test_title_formula_has_genre_word():
    """Guard жанра матчит слово жанра в заголовке (watchdog.GENRE_IN_TITLE):
    формула LLM обязана включать слово жанра, иначе phonk-выпуск guard не увидит."""
    with tempfile.TemporaryDirectory() as d:
        p_lofi = idea.build_prompt("anime lofi", date(2026, 10, 13), Path(d))
        p_phonk = idea.build_prompt("chill phonk", date(2026, 10, 13), Path(d))
    assert "lofi" in p_lofi.lower()
    assert "phonk" in p_phonk.lower()


def test_m1_duplicate_scene_titles_blocked():
    """M1 (аудит 18.10): на канале ушли дубли сцен long-form — «Cozy Halloween Night Train» x2 (14.10),
    «Anime Nights» x2 (12.10), «… Sunset Rooftop» x2 (16.10). Шаблонность = риск inauthentic content."""
    rec = [{"date": "2026-10-14", "title": "Cozy Halloween Night Train 🎃 Lofi Beats to Relax / Sleep to | 1 Hour"},
           {"date": "2026-10-12", "title": "Anime Nights 🌸 Chill Lofi Beats to Study and Relax to"},
           {"date": "2026-10-16", "title": "Cozy Sunset Rooftop 🎃 Lofi Beats to Study and Relax to | 1 Hour"}]
    d = date(2026, 10, 17)
    assert idea.dup_title("Cozy Halloween Night Train 🎃 Lofi Beats to Study & Relax to", rec, d)
    assert idea.dup_title("Anime Nights 🌙 Chill Lofi Beats to Study and Relax to", rec, d)
    assert idea.dup_title("Autumn Sunset Rooftop 🎃 Phonk Beats to Relax and Drift to", rec, d)
    assert idea.dup_title("Pumpkin Night Train 🎃 Cozy Lofi Beats to Study and Relax to", rec, d), "та же сцена: night train"
    for ok in ("Rainy Tokyo Pumpkin Café 🎃 Cozy Lofi Beats to Study & Relax to", "Autumn Café Window 🎃 Phonk Beats",
               "Anime Sunset Study Sessions 🌸 Chill Lofi Beats to Study and Relax to"):
        assert not idea.dup_title(ok, rec, d), ok
    assert not idea.dup_title("Cozy Halloween Night Train 🎃 Lofi Beats", rec, date(2026, 11, 1)), "окно 14 дней"
    with tempfile.TemporaryDirectory() as t:
        idea.remember_title("A", date(2026, 10, 1), Path(t))
        idea.remember_title("B", date(2026, 10, 20), Path(t))
        assert [r["title"] for r in idea.recent_titles(Path(t))] == ["A", "B"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
