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


def test_mux_copies_tp_checked_audio():
    """t_fef617d9: алимитер ДО AAC-кодера не видит овершут кодера (run 40408005493: 03c TP -1.4, 04b +6.5).
    Оба mux-пути копируют звук (-c:a copy), закодированный encode_audio с замером TP на выходе кодера."""
    src = (HERE / "04_assemble.py").read_text(encoding="utf-8")
    assert src.count('"-c:a", "copy"') == 2, "оба mux-пути (loop и static) должны копировать готовый AAC"
    assert '"-b:a", "192k"' not in src, "перекодирование звука в mux вернулось"
    assert "encode_audio(track_norm" in src


PHONK_HOT = ("aevalsrc=0.9*clip(3*sin(2*PI*45*t)*exp(-2*mod(t\\,0.5))\\,-1\\,1)+0.3*sgn(sin(2*PI*800*t))*exp(-20*mod(t\\,0.25))"
             "|0.9*clip(3*sin(2*PI*45*t+0.3)*exp(-2*mod(t\\,0.5))\\,-1\\,1)+0.3*sgn(sin(2*PI*540*t))*exp(-20*mod(t\\,0.25))"
             ":s=48000:d=8")


def test_encode_audio_tp_after_codec():
    """RED на старом пути: 808 + квадратный cowbell, WAV TP -3.7 -> alimiter -1.5 + AAC 192k = +1.1 dBTP (клиппинг 04b)."""
    import re, subprocess, tempfile
    import quality_gate as qg
    asm = _load("asm_enc", "04_assemble.py")
    with tempfile.TemporaryDirectory() as td:
        w, o = f"{td}/h.wav", f"{td}/o.m4a"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", PHONK_HOT,
                        "-af", "volume=-6dB,alimiter=limit=-2.5dB:level=false", "-c:a", "pcm_s16le", w], check=True)
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", w,
                        "-af", "alimiter=limit=-1.5dB:level=false", "-c:a", "aac", "-b:a", "192k", o], check=True)
        old = asm.tp_of(o)
        assert old > qg.MAX_TP, f"фикстура больше не воспроизводит овершут AAC: {old}"
        new = asm.encode_audio(w, o)
        print(f"AAC TP: старый путь {old:+.1f}, encode_audio {new:+.1f}")
        assert new <= qg.MAX_TP and asm.tp_of(o) == new, new


def test_signature_absent_in_final_gate():
    """Сигнатура карточки: quality_gate.objective на video.mp4 после 04_assemble не даёт «true peak ... клиппинг»."""
    import os, subprocess, tempfile
    import quality_gate as qg
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        Image.new("RGB", (640, 360), (40, 40, 80)).save(d / "cover.png")
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", PHONK_HOT,
                        "-c:a", "libmp3lame", "-b:a", "192k", str(d / "track.mp3")], check=True)
        asm = _load("asm_sig", "04_assemble.py")
        with patch.dict(os.environ, {"ACF_RUN_DIR": td}):
            asm.main()
        why, m = qg.objective(str(d / "video.mp4"), "chill phonk")
        print(f"video.mp4 phonk-фикстура: TP={m['tp']} I={m['i']}")
        assert not [w for w in why if "true peak" in w], why


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
