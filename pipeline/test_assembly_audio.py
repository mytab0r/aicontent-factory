#!/usr/bin/env python3
"""t_ba72c7aa follow-up: (1) mux в 04_assemble лимитирует аудио (04b клиппинг TP +0.2);
(2) сегменты банка нормализуются loudnorm до склейки (03c LU-скачок 4.7 внутри сегмента)."""
import importlib.util
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


def test_norm_segments_runs_loudnorm_per_segment(tmp_path=None):
    br = _load("br_norm", "bank_release.py")
    import quality_gate
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = Path(cmd[-1])
        out.write_bytes(b"x")
        return SimpleNamespace(returncode=0, stderr="")

    p1 = Path("/tmp/n1.mp3"); p2 = Path("/tmp/n2.mp3")
    with patch.object(br.subprocess, "run", fake_run):
        br._norm_segments([p1, p2], log=lambda *a, **k: None)
    assert len(calls) == 2
    for c in calls:
        assert c[0] == "ffmpeg" and "loudnorm" in " ".join(c)
        assert f"I={quality_gate.LUFS_TARGET:g}" in " ".join(c)
        assert "TP=-2" in " ".join(c)


def test_norm_segments_keeps_original_on_failure():
    br = _load("br_norm2", "bank_release.py")
    import importlib

    def fake_run(cmd, **kw):
        return SimpleNamespace(returncode=1, stderr="boom")

    p = Path("/tmp/n3.mp3"); p.write_bytes(b"orig")
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
