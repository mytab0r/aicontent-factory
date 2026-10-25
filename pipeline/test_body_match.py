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


def test_body_match_aligns_body_level_to_first_segment():
    m = _load("acf_music03_bm", HERE / "03_music.py")
    calls = []
    m.body_lufs = lambda p, sec=60.0: -18.0 if Path(p).name == "a.mp3" else -20.0
    m._apply_gain = lambda p, g: calls.append(("gain", Path(p).name, round(g, 2)))
    gains = m.body_match(["/r/a.mp3", "/r/b.mp3", "/r/c.mp3"], log=lambda *a: None)
    assert gains == [0.0, 2.0, 2.0], gains
    assert ("gain", "b.mp3", 2.0) in calls and ("gain", "c.mp3", 2.0) in calls


def test_body_match_uses_gate_loudness_metric():
    """run 40127996482: тела выровнены по RMS (gain +0.64), гейт A18 (short-term LUFS) увидел 4.6 LU.
    Регресс: бас 60 Гц и верх 3 кГц с РАВНЫМ RMS — K-weighting разводит их на несколько LU.
    После body_match медианы short-term LUFS тел обязаны совпасть (<= 1 LU)."""
    import subprocess
    import tempfile
    m = _load("acf_music03_bm4", HERE / "03_music.py")
    with tempfile.TemporaryDirectory() as td:
        lo, hi = f"{td}/lo.mp3", f"{td}/hi.mp3"
        for f, hz in ((lo, 60), (hi, 3000)):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=f={hz}:d=90",
                            "-af", "volume=-12dB", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", f], check=True)
        before = abs(m.body_lufs(lo) - m.body_lufs(hi))
        assert before > 2.0, before  # равный RMS, разная громкость по метрике гейта
        m.body_match([lo, hi], log=lambda *a: None)
        after = abs(m.body_lufs(lo) - m.body_lufs(hi))
        assert after <= 1.0, (before, after)


def test_body_match_skips_within_tolerance():
    m = _load("acf_music03_bm2", HERE / "03_music.py")
    m.body_lufs = lambda p, sec=60.0: -18.0
    applied = []
    m._apply_gain = lambda p, g: applied.append(g)
    gains = m.body_match(["/r/a.mp3", "/r/b.mp3"], log=lambda *a: None)
    assert gains == [0.0, 0.0] and not applied


def test_prep_segments_runs_body_before_edge():
    m = _load("acf_music03_bm3", HERE / "03_music.py")
    order = []
    m.trim_fade_tails = lambda ps, log=print: order.append("trim")
    m.trim_fade_head = lambda ps, log=print: order.append("head")
    m.body_match = lambda ps, log=print: (order.append("body"), [0.0] * len(ps))[1]
    m.edge_match = lambda ps, log=print: (order.append("edge"), [0.0] * len(ps))[1]
    m.prep_segments(["/r/a.mp3", "/r/b.mp3"], log=lambda *a: None)
    assert order == ["trim", "head", "body", "edge"], order


if __name__ == "__main__":  # t_110fa85f: CI запускает файл как скрипт — без блока def test_* не выполняются
    _fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for _f in _fns:
        _f()
        print("ok", _f.__name__)
    print(f"PASS {len(_fns)} tests")
