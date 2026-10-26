#!/usr/bin/env python3
"""t_ba72c7aa (run 40253826993): 03 music из банка 20 x 180 с не влез в 20 мин. Замер на 32 ядрах:
_norm_segments 157 с, trim tails/head 105 с, concat 65 с, loudnorm_2pass 289 с (из них анализ 127 с) - всё
последовательно. Фикс: независимые сегменты параллельно (pmap), 1-й проход мастера = ebur128."""
import importlib.util
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def test_pmap_parallel_and_ordered():
    m = _load("acf_music_speed", "03_music.py")
    seen = set()

    def f(x):
        seen.add(threading.get_ident())
        time.sleep(0.2)
        return x * 2
    t = time.time()
    assert m.pmap(f, range(8)) == [0, 2, 4, 6, 8, 10, 12, 14]
    assert time.time() - t < 1.0 and len(seen) > 1, "сегменты обрабатываются последовательно"


def test_per_segment_steps_use_pmap():
    src = (HERE / "03_music.py").read_text(encoding="utf-8")
    for fn in ("def trim_fade_tails", "def trim_fade_head", "def body_match", "def concat_tracks"):
        body = src[src.index(fn):]
        body = body[:body.index("\ndef ", 1)]
        assert "pmap(" in body, f"{fn}: последовательный цикл по сегментам"
    br = (HERE / "bank_release.py").read_text(encoding="utf-8")
    nb = br[br.index("def _norm_segments"):br.index("def flatten_blocks")]
    assert "pmap(" in nb


def test_master_first_pass_is_ebur128():
    br = (HERE / "bank_release.py").read_text(encoding="utf-8")
    body = br[br.index("def loudnorm_2pass"):br.index("def master_final")]
    assert "print_format=json" not in body, "анализ loudnorm 127 с на часе: 1-й проход = ebur128"
    assert "ebur128=peak=true" in body


if __name__ == "__main__":
    _fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for _f in _fns:
        _f()
        print("ok", _f.__name__)
    print(f"PASS {len(_fns)} tests")
