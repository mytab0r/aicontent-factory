#!/usr/bin/env python3
"""t_ba72c7aa follow-up: (1) mux в 04_assemble лимитирует аудио (04b клиппинг TP +0.2);
(2) сегменты банка нормализуются loudnorm до склейки (03c LU-скачок 4.7 внутри сегмента)."""
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, HERE / path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_mux_uses_limiter():
    src = (HERE / "04_assemble.py").read_text(encoding="utf-8")
    assert src.count("alimiter") == 2, "оба mux-пути (loop и static) должны лимитировать аудио"
    assert "limit=-1.5dB" in src


def test_norm_segments_static_gain_no_loudnorm(tmp_path=None):
    """t_5dbfa67a: сегмент = статический volume к LUFS_TARGET + alimiter, без loudnorm (давит LRA)."""
    br = _load("br_norm", "bank_release.py")
    import mastering
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"x")
        return SimpleNamespace(returncode=0, stderr="")

    p1 = Path("/tmp/n1.mp3"); p2 = Path("/tmp/n2.mp3")
    with patch.object(br.subprocess, "run", fake_run), \
            patch.object(mastering, "measure", lambda f: {"i": -20.0, "lra": 9.0, "tp": -3.0}):
        br._norm_segments([p1, p2], log=lambda *a, **k: None)
    assert len(calls) == 2
    import quality_gate
    for c in calls:
        j = " ".join(c)
        assert c[0] == "ffmpeg" and "loudnorm" not in j, "loudnorm вернулся в _norm_segments"
        assert f"volume={quality_gate.LUFS_TARGET + 20.0:.2f}dB" in j and "alimiter" in j


def test_norm_segments_keeps_lra_real_audio():
    """RED на старом коде: динамичный сегмент (LRA 12.4) после loudnorm -> 6.9; статический gain держит LRA."""
    import shutil, subprocess as sp
    if not shutil.which("ffmpeg"):
        print("skip: нет ffmpeg"); return
    import tempfile, mastering, quality_gate as qg
    br = _load("br_norm_real", "bank_release.py")
    from test_master_lra import make_dyn
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "raw.mp3"; seg = Path(td) / "seg.mp3"
        make_dyn(raw, dur=180)
        mastering.master(str(raw), str(seg), genre="anime lofi")
        before = mastering.measure(str(seg))
        br._norm_segments([seg], log=print)
        after = mastering.measure(str(seg))
        assert after["lra"] >= before["lra"] - 1.0, f"LRA сегмента {before['lra']} -> {after['lra']} (каша)"
        assert qg.MIN_I <= after["i"] <= qg.MAX_I, f"громкость сегмента {after['i']} вне гейта"
        print(f"norm_segments: LRA {before['lra']} -> {after['lra']}, I {after['i']}")


def test_norm_segments_keeps_original_on_failure():
    br = _load("br_norm2", "bank_release.py")
    import importlib

    def fake_run(cmd, **kw):
        return SimpleNamespace(returncode=1, stderr="boom")

    p = Path("/tmp/n3_" + str(os.getpid()) + ".mp3"); p.write_bytes(b"orig")
    logs = []
    with patch.object(br.subprocess, "run", fake_run):
        br._norm_segments([p], log=logs.append)
    assert p.read_bytes() == b"orig"  # битая нормализация не портит сегмент
    assert any("не удался" in str(x) for x in logs)


def test_assemble_static_passes_tp_and_loudness_gate():
    """t_c68d7f9c: горячий трек (~-4 LUFS, клиппинг) после 04_assemble (статичный путь) в гейте I и TP.
    RED на старом коде: только alimiter, громкость вне MIN_I..MAX_I."""
    import os
    import subprocess
    import tempfile
    import quality_gate as qg
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        Image.new("RGB", (640, 360), (40, 40, 80)).save(d / "cover.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=330:duration=8:sample_rate=48000,volume=7.5",
                        "-c:a", "libmp3lame", "-b:a", "192k", str(d / "track.mp3")], check=True)
        asm = _load("asm_tp", "04_assemble.py")
        with patch.dict(os.environ, {"ACF_RUN_DIR": td}):
            asm.main()
        e = qg.ff(str(d / "video.mp4"), "ebur128=peak=true")
        import re
        tp = float(re.findall(r"Peak:\s+(-?[\d.]+|-inf)", e)[-1].replace("-inf", "-200"))
        li = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", e)[-1])
        print(f"video: I={li} TP={tp}")
        assert tp <= qg.MAX_TP, tp
        assert qg.loud_why(li) == [], li


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print(f.__name__, "OK")
    print(f"{len(fns)}/{len(fns)} passed")
