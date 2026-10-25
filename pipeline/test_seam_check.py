#!/usr/bin/env python3
"""Тесты seam_check.py + loop_build.py (спека spec-seamless-loop.md §5, §8).

Без GPU: синтетика через ffmpeg lavfi, кадр 320x180 (§8):
- идеальный цикл 48 кадров            -> PASS A/B;
- цикл без возврата (кадры 0..40)     -> FAIL B1 (скачок);
- дубль последнего кадра (0..48)      -> FAIL B2;
- статика (color=gray)                -> FAIL B3.
- concat 48 кадров x K=10 -> C2/C3 зелёные, keyframe = 10.

seam_check.py реализует метрики A/B на чистом ffmpeg: кадры вынимаются в PNG,
d_i считается signalstats-YDIF... упрощённо: попарные PSNR считаются по Y-
плейнам через numpy (никаких новых зависимостей сверх numpy; ffmpeg только
декодирует кадры в raw gray).
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import seam_check
import loop_build


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    assert p.returncode == 0, f"{cmd} failed:\n{p.stderr[-2000:]}"


def _synth(n_frames: int, pattern: str = "wave", fps: int = 24) -> list[np.ndarray]:
    """Синтетический клип 320x180: wave -> движущаяся синусоида, static -> серый."""
    if pattern == "wave":
        src = (
            "color=gray:s=320x180:r=24,geq=lum='128+60*sin(2*PI*(X/320+T/2))'"
            ":cb=128:cr=128"
        )
    else:
        src = "color=gray:s=320x180:r=24"
    cmd = [
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", src,
        "-frames:v", str(n_frames), "-pix_fmt", "gray", "-f", "rawvideo", "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, dtype=np.uint8)
    return list(frames.reshape(n_frames, 180, 320))


# ---- A: замыкание raw-клипа (§5 A) ----

def test_closure_pass_on_wave():
    frames = _synth(48, "wave")
    m = seam_check.closure_metrics(frames[-1], frames[0])
    assert m["psnr"] >= 35.0 or m["ssim"] >= 0.98, m


def test_closure_fail_on_jump():
    first = _synth(1, "wave")[0]
    # кадр из середины периода: точно не совпадает с first
    mid = _synth(24, "wave")[-1]
    m = seam_check.closure_metrics(mid, first)
    assert not (m["psnr"] >= 35.0 or m["ssim"] >= 0.98), m


# ---- B: метрики шва loop.mp4 (§5 B1-B4) ----

def _check(frames):
    return seam_check.seam_metrics(frames)


def test_seam_pass_ideal_loop():
    frames = _synth(48, "wave")
    rep = _check(frames)
    assert rep["ok"], json.dumps(rep["failures"], ensure_ascii=False)


def test_seam_fail_b1_jump():
    # 0..41: конец волны не совпадает с началом -> скачок
    frames = _synth(42, "wave")
    rep = _check(frames)
    b1 = next(f for f in rep["failures"] if f["id"] == "B1")
    assert not rep["ok"]


def test_seam_fail_b2_duplicate():
    frames = _synth(48, "wave")
    frames.append(frames[0].copy())  # дубль первого кадра в хвосте
    rep = _check(frames)
    b2 = [f for f in rep["failures"] if f["id"] == "B2"]
    assert not rep["ok"] and b2


def test_seam_fail_b3_static():
    frames = _synth(48, "static")
    rep = _check(frames)
    b3 = [f for f in rep["failures"] if f["id"] == "B3"]
    assert not rep["ok"] and b3


# ---- encode/concat (§4 шаг 4, §5 C) ----

def test_encode_gop_and_dup_cut():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        frames_dir = out / "frames"
        frames_dir.mkdir()
        frames = _synth(48, "wave")
        # хвост = дубль первого кадра: encode обязан его отрезать (§4 шаг 4)
        frames.append(frames[0].copy())
        for i, f in enumerate(frames):
            (frames_dir / f"{i:05d}.png").write_bytes(
                _png_from_gray(f))
        loop = out / "loop.mp4"
        n_kept = loop_build.encode_loop(frames_dir, loop, fps=24,
                                        overlay_text=None)
        assert n_kept == 48, n_kept
        info = loop_build.probe(loop)
        assert info["codec"] == "h264"
        assert info["width"] == 320 and info["height"] == 180
        assert info["r_frame_rate"] == info["avg_frame_rate"]
        kf = loop_build.keyframe_count(loop)
        assert kf == 1, f"один GOP: keyframe={kf}"
        # хвост после среза не равен первому кадру (B2-защита)
        rep = seam_check.check_file(loop)
        assert rep["ok"], json.dumps(rep["failures"], ensure_ascii=False)


def _png_from_gray(gray: np.ndarray) -> bytes:
    """Минимальный PNG-писатель для gray8 (чтобы не тянуть Pillow в тест)."""
    import zlib
    import struct

    h, w = gray.shape
    raw = b"".join(b"\x00" + gray[i].tobytes() for i in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_concat_final_c_metrics():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        frames_dir = out / "frames"
        frames_dir.mkdir()
        frames = _synth(48, "wave")
        for i, f in enumerate(frames):
            (frames_dir / f"{i:05d}.png").write_bytes(_png_from_gray(f))
        loop = out / "loop.mp4"
        loop_build.encode_loop(frames_dir, loop, fps=24, overlay_text=None)
        # трек 60с: T=60, цикл 2с -> K=30 повторов
        wav = out / "track.wav"
        _run(["ffmpeg", "-v", "error", "-f", "lavfi",
              "-i", "sine=frequency=440:duration=60", "-ar", "44100",
              str(wav)])
        final = out / "final.mp4"
        rep = loop_build.build_final(loop, wav, final, fps=24, T=60.0,
                                     expect_size=(320, 180))
        info = rep["probe"]
        assert abs(info["duration"] - 60.0) <= 0.1, info["duration"]
        assert info["codec"] == "h264" and info["audio"] == "aac"
        assert rep["keyframes"] in (30, 31), rep["keyframes"]
        assert rep["dts_increasing"], rep
        assert rep["stderr_clean"], rep.get("stderr")[:2000]


# ---- selftest seam_check (§8: внутри один assert-самотест) ----

def test_seam_check_selftest():
    assert seam_check.selftest() is True


if __name__ == "__main__":
    test_closure_pass_on_wave()
    test_closure_fail_on_jump()
    test_seam_pass_ideal_loop()
    test_seam_fail_b1_jump()
    test_seam_fail_b2_duplicate()
    test_seam_fail_b3_static()
    test_encode_gop_and_dup_cut()
    test_concat_final_c_metrics()
    test_seam_check_selftest()
    print("all seam tests passed")
