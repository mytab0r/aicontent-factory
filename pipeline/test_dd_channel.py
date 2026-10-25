#!/usr/bin/env python3
"""Тесты: D&D ambience профиль канала (конфиг + выбор сцены + idea-промпт).

Запуск: python3 pipeline/test_dd_channel.py
Покрывает новую логику 01_idea.py/dd_channel.py до изменения прода (TDD).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dd_channel


def test_load_scenes():
    scenes = dd_channel.load_scenes()
    assert len(scenes) >= 4, f"need >=4 scenes, got {len(scenes)}"
    for s in scenes:
        assert {"name", "music_prompt", "cover_prompt", "title_scene"} <= set(s), s
        assert s["music_prompt"].strip(), s
        assert "no vocals" in s["music_prompt"] or "instrumental" in s["music_prompt"], s


def test_scene_rotation_deterministic():
    scenes = dd_channel.load_scenes()
    with tempfile.TemporaryDirectory() as td:
        state = Path(td) / "scene_idx.txt"
        a = dd_channel.next_scene(state)
        b = dd_channel.next_scene(state)
        c = dd_channel.next_scene(state)
        assert a["name"] != b["name"] or len(scenes) == 1
        # rotation wraps cleanly and never repeats until full cycle
        seen = [a["name"], b["name"], c["name"]]
        assert len(seen) == len(set(seen)), f"repeat within cycle: {seen}"


def test_channel_profile():
    p = dd_channel.profile()
    assert p["channel_id_env"] == "DD_CHANNEL_ID"
    assert "dnd" in p["name"].lower() or "tavern" in p["name"].lower()
    assert p["shorts_per_week"] == (3, 5)


def test_idea_prompt_mentions_scene():
    scenes = dd_channel.load_scenes()
    text = dd_channel.idea_prompt(scenes[0])
    assert scenes[0]["title_scene"] in text
    assert "JSON" in text


if __name__ == "__main__":
    test_load_scenes()
    test_scene_rotation_deterministic()
    test_channel_profile()
    test_idea_prompt_mentions_scene()
    print("all dd_channel tests passed")
