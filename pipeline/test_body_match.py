# -*- coding: utf-8 -*-
"""t_cron1024: тело сегмента выравнивается по громкости (body_match) ДО edge_match.
Причина: краевая рампа edge_match правит только первые 30 с стыка; блоки 60 с в середине
сегментов остаются с раскидом до 6 дБ -> гейт 03c FAIL «скачок громкости между блоками»
(run 40075415222: 4.9 и 5.8 LU на 483/543 с). Класс закрыт выравниванием тел, не ослаблением гейта."""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).parent


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, fn)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def test_body_match_aligns_body_rms_to_first_segment():
    m = _load("acf_music03_bm", HERE / "03_music.py")
    calls = []

    def fake_rms(path, side, sec=5.0):
        calls.append((Path(path).name, side, sec))
        return -18.0 if (side == "body" and Path(path).name == "a.mp3") else -20.0

    m.edge_rms = fake_rms
    m._apply_gain = lambda p, g: calls.append(("gain", Path(p).name, round(g, 2)))
    paths = ["/r/a.mp3", "/r/b.mp3", "/r/c.mp3"]
    gains = m.body_match(paths, log=lambda *a: None)
    assert gains == [0.0, 2.0, 2.0], gains
    assert ("gain", "b.mp3", 2.0) in calls and ("gain", "c.mp3", 2.0) in calls
    assert any(side == "body" and sec == 60.0 for _, side, sec in calls)


def test_body_match_skips_within_tolerance():
    m = _load("acf_music03_bm2", HERE / "03_music.py")
    m.edge_rms = lambda p, s, sec=5.0: -18.0
    applied = []
    m._apply_gain = lambda p, g: applied.append(g)
    gains = m.body_match(["/r/a.mp3", "/r/b.mp3"], log=lambda *a: None)
    assert gains == [0.0, 0.0] and not applied


def test_prep_segments_runs_body_before_edge():
    m = _load("acf_music03_bm3", HERE / "03_music.py")
    order = []
    m.trim_fade_tails = lambda ps, log=print: order.append("trim")
    m.body_match = lambda ps, log=print: (order.append("body"), [0.0] * len(ps))[1]
    m.edge_match = lambda ps, log=print: (order.append("edge"), [0.0] * len(ps))[1]
    m.prep_segments(["/r/a.mp3", "/r/b.mp3"], log=lambda *a: None)
    assert order == ["trim", "body", "edge"], order
