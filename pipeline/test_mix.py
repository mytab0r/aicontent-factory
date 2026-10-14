#!/usr/bin/env python3
"""Микс ~1 ч из нескольких цельных треков ACE-Step 1.5 + главы-треклист в описании.

Ресёрч 13.10: инструментальные хиты ниши = 1-4 ч, у 2/3 треклист с 0:00; наш 8:03 ниже нормы.
Запуск: python3 pipeline/test_mix.py
"""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


music = _load("music_mix", "03_music.py")


def test_mix_fills_target_with_actual_durations():
    made = []
    def gen(i):
        made.append(i)
        return f"t{i}.mp3"
    # модель отдаёт меньше запрошенного (600 -> 482 с), считаем по факту
    paths, durs = music.plan_mix(3600, gen, lambda p: 482.0)
    assert len(paths) == 8 and sum(durs) >= 3600          # 8 x 482 = 3856
    assert made == list(range(8))


def test_mix_stops_on_time_budget_but_keeps_tracks():
    clock = iter([0, 600, 1300])  # старт; после t0 (600+600<=1500); после t1 1300+650>1500 -> стоп
    paths, _ = music.plan_mix(3600, lambda i: f"t{i}", lambda p: 400.0,
                              budget_sec=1500, now=lambda: next(clock))
    assert paths == ["t0", "t1"]


def test_mix_max_tracks_cap():
    paths, _ = music.plan_mix(10**6, lambda i: i, lambda p: 1.0, max_tracks=3)
    assert len(paths) == 3


def test_chapters_start_at_zero_and_format_hours():
    ch = music.chapters([482.0, 482.0, 3000.0], ["A", "B", "C"])
    assert ch == ["0:00 A", "8:02 B", "16:04 C"]
    assert music.chapters([3700, 10], ["x", "y"])[1] == "1:01:40 y"


def test_track_names_unique_and_deterministic():
    a = music.track_names(8, seed=5)
    assert len(set(a)) == 8 and a == music.track_names(8, seed=5)


def test_description_gets_tracklist():
    pub = _load("pub_mix", "05_publish.py")
    d = pub.full_description("Cozy rain.", ["0:00 A", "8:02 B", "16:04 C"])
    assert "Tracklist:\n0:00 A\n8:02 B\n16:04 C" in d
    assert d.index("Tracklist") < d.index("#lofi")
    assert "Tracklist" not in pub.full_description("x")  # без глав (1 трек) — как раньше


def test_title_gets_real_length_label():
    pub = _load("pub_len", "05_publish.py")
    t = "Rainy Tokyo Pumpkin Caf\u00e9 \U0001f383 Cozy Lofi Beats to Study & Relax"
    assert pub.title_with_length(t, 3856) == t + " | 1 Hour"
    assert pub.title_with_length(t, 7300) == t + " | 2 Hours"
    assert pub.title_with_length(t, 482) == t  # < ~55 мин: без метки (не врём о длине)
    assert pub.title_with_length("Cafe 1 Hour Lofi", 3700) == "Cafe 1 Hour Lofi"  # уже есть
    long = "x" * 99
    assert len(pub.title_with_length(long, 3700)) <= 100


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
