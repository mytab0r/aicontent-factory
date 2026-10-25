# -*- coding: utf-8 -*-
"""t_cron1024b: финальная склейка банка мастерится как сгенерированный микс (mastering.master +
fade_end). Без этого TP склейки > -1 dBTP (клиппинг, run 40087548227) — сегменты мастерились
поодиночке, concat перекодирует и поднимает пики; гейт 03c честно ловит. Гейт не ослаблен."""
import importlib.util
import re
import subprocess as sp
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, fn)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _br():
    return _load("bank_release_m", HERE / "bank_release.py")


def test_assemble_calls_master_final():
    br = _br()
    m = br._music_mod()
    calls = []
    m.prep_segments = lambda ps, log=print: calls.append("prep")
    m.concat_tracks = lambda ps, out, xfade=m.XFADE: calls.append("concat")
    m._probe_sec = lambda p: 180.0
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td)
        paths = [rd / "a.mp3", rd / "b.mp3"]
        for p in paths:
            p.write_bytes(b"x")
        metas = [{"name": "a", "seed": 1, "prompt": "p"}, {"name": "b", "seed": 2, "prompt": "p"}]
        try:
            br.master_final
        except AttributeError:
            raise AssertionError("master_final отсутствует: склейка банка не мастерится (TP > -1)")
        real = br.master_final
        br.master_final = lambda path, genre: calls.append(("master", Path(path).name, genre))
        try:
            br.assemble(paths, rd, metas, "anime lofi")
        finally:
            br.master_final = real
        assert ("master", "track.mp3", "anime lofi") in calls, calls


def test_master_final_tp_on_real_audio():
    """Реальный ffmpeg-звук: склейка с master_final держит пик ниже порога гейта (-0.9 dB, TP≈peak для синуса)."""
    for name in [n for n in list(sys.modules) if n.startswith("bank_release_m") or n == "acf_music03"]:
        del sys.modules[name]  # first test leaves concat/prep stubs cached - need a clean module
    br = _br()
    with tempfile.TemporaryDirectory() as td:
        segs = []
        for i in range(2):
            p = f"{td}/s{i}.mp3"
            sp.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=220:duration=180,volume=-1dB",
                    "-af", "afade=t=in:d=2,afade=t=out:st=172:d=6",
                    "-c:a", "libmp3lame", "-b:a", "192k", p], check=True)
            segs.append(Path(p))
        out = Path(td) / "track.mp3"
        try:
            br.master_final
        except AttributeError:
            raise AssertionError("master_final отсутствует: склейка банка не мастерится (TP > -1)")
        br.assemble(segs, Path(td), [{"name": f"s{i}", "seed": i, "prompt": "p"} for i in range(2)], "anime lofi")
        assert out.exists()
        e = sp.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(out),
                    "-af", "astats=measure_overall=Peak_level:measure_perchannel=none", "-f", "null", "-"],
                   capture_output=True, text=True).stderr
        peak = float(re.findall(r"Peak level dB: (-?[0-9.]+)", e)[-1])
        assert peak <= -0.9, f"Peak {peak} dB — выше порога гейта (TP примерно равен peak для синуса)"


if __name__ == "__main__":  # t_110fa85f: CI запускает файл как скрипт — без блока def test_* не выполняются
    _fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for _f in _fns:
        _f()
        print("ok", _f.__name__)
    print(f"PASS {len(_fns)} tests")
