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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
