#!/usr/bin/env python3
"""Шаги 4/6/7 спеки seamless-loop: encode loop.mp4, concat до длины трека,
финальные проверки C1-C4 (spec-seamless-loop.md).

Использование:
    python3 loop_build.py encode <frames_dir> <loop.mp4> --fps 24
        [--overlay-text "AI-generated / synthetic content"]
    python3 loop_build.py final <loop.mp4> <track> <final.mp4> --fps 24
"""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

OVERLAY_TEXT = "AI-generated / synthetic content"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:6])}... failed:\n{p.stderr[-3000:]}")
    return p


def probe(path: str | Path) -> dict:
    """ffprobe: codec/width/height/fps/duration/audio одним вызовом."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,codec_type,width,height,r_frame_rate,"
         "avg_frame_rate,pix_fmt,sample_aspect_ratio",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    info: dict = {}
    for st in j.get("streams", []):
        if st.get("codec_type") == "video":
            info.update(codec=st.get("codec_name"), width=st["width"],
                        height=st["height"], pix_fmt=st.get("pix_fmt"),
                        r_frame_rate=st.get("r_frame_rate"),
                        avg_frame_rate=st.get("avg_frame_rate"),
                        sar=st.get("sample_aspect_ratio"))
        elif st.get("codec_type") == "audio":
            info["audio"] = st.get("codec_name")
    info["duration"] = float(j.get("format", {}).get("duration", 0) or 0)
    return info


def count_frames(path: str | Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return int(out or 0)


def keyframe_count(path: str | Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=pict_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout
    return out.count("I")


def frame_count_in_dir(frames_dir: Path) -> int:
    return len(list(frames_dir.glob("*.png")))


def mse_of_pair(a_img: Path, b_img: Path) -> float:
    """MSE Y-плейнов двух PNG (для среза дубля, §4 шаг 4)."""
    ps = []
    for p in (a_img, b_img):
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(p), "-pix_fmt", "gray",
             "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
        ps.append(raw)
    if len(ps[0]) != len(ps[1]) or not ps[0]:
        return float("inf")
    import numpy as np
    a = np.frombuffer(ps[0], dtype=np.uint8).astype(np.float64)
    b = np.frombuffer(ps[1], dtype=np.uint8).astype(np.float64)
    return float(np.mean((a - b) ** 2))


def encode_loop(frames_dir: Path, out_path: Path, fps: int,
                overlay_text: str | None = OVERLAY_TEXT,
                dup_psnr_threshold: float = 50.0) -> int:
    """Шаг 4: frames/*.png -> loop.mp4. Ровно один GOP, closed, без B-frames.

    Если последний кадр совпадает с первым (PSNR >= 50 dB) — он отрезается.
    Возвращает число кадров в loop.mp4.
    """
    n = frame_count_in_dir(frames_dir)
    assert n >= 2, f"нет кадров в {frames_dir}"
    if mse_of_pair(frames_dir / f"{n - 1:05d}.png",
                   frames_dir / "00000.png") <= 255.0 ** 2 / 10 ** (dup_psnr_threshold / 10):
        n -= 1  # дубль первого кадра в хвосте — срезать
    vf = [f"fps={fps}", "format=yuv420p"]
    if overlay_text:
        escaped = overlay_text.replace(":", "\\:").replace("'", "\\'")
        vf.append("drawtext=text='%s':x=(w-text_w)/2:y=h-text_h-24:"
                  "fontsize=28:fontcolor=white@0.6:box=1:boxcolor=black@0.3:boxborderw=8" % escaped)
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-framerate", str(fps),
        "-i", str(frames_dir / "%05d.png"),
        "-vf", ",".join(vf),
        "-frames:v", str(n),
        "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p",
        "-g", str(n), "-keyint_min", str(n), "-sc_threshold", "0", "-bf", "0",
        "-x264-params", "open-gop=0",
        "-video_track_timescale", str(fps * 1000),
        "-an", str(out_path),
    ]
    _run(cmd)
    kept = count_frames(out_path)
    assert kept == n, f"encode дал {kept} кадров, ожидалось {n}"
    return kept


def build_final(loop: Path, track: Path, final: Path, fps: int,
                T: float | None = None,
                expect_size: tuple[int, int] = (1920, 1080)) -> dict:
    """Шаги 6-7: concat loop.mp4 K раз до длины трека + аудио, проверки C1-C4.

    Возвращает отчёт {k, probe, keyframes, dts_increasing, stderr_clean, ...};
    бросает AssertionError при провале любой проверки C.
    """
    info = probe(loop)
    assert info["codec"] == "h264" and info["pix_fmt"] == "yuv420p", info
    assert (info["width"], info["height"]) == expect_size, info
    r, _ = info["r_frame_rate"].split("/")
    a, b = info["avg_frame_rate"].split("/")
    assert info["r_frame_rate"] == info["avg_frame_rate"], "не CFR"
    fps_num = float(r) if "/" in info["r_frame_rate"] else float(info["r_frame_rate"])
    fps = int(round(fps_num))

    track_dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(track)], capture_output=True, text=True,
        check=True).stdout.strip())
    T = T if T is not None else track_dur
    loop_dur = info["duration"]
    k = max(1, math.ceil(T / loop_dur))

    workdir = final.parent
    list_txt = workdir / "concat_list.txt"
    list_txt.write_text("".join(f"file '{loop.resolve()}'\n" for _ in range(k)),
                        encoding="utf-8")
    p = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(list_txt), "-i", str(track),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-t", f"{T:.3f}",
         "-movflags", "+faststart", str(final)],
        capture_output=True, text=True)
    stderr = p.stderr or ""
    assert p.returncode == 0, f"concat+mux failed:\n{stderr[-3000:]}"
    bad = [ln for ln in stderr.splitlines()
           if "Non-monotonic DTS" in ln or "timestamp" in ln.lower()]
    stderr_clean = not bad

    finfo = probe(final)
    # C1
    assert finfo["width"] == expect_size[0] and finfo["height"] == expect_size[1], finfo
    assert finfo["codec"] == "h264" and finfo["audio"] == "aac", finfo
    # C2
    assert abs(finfo["duration"] - T) <= 0.1, (finfo["duration"], T)

    # C3: dts строго возрастает, Δpts = 1/fps, число keyframe = K (±1 из-за -t)
    pkts = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts,dts,flags", "-of", "csv=p=0", str(final)],
        capture_output=True, text=True, check=True).stdout.strip().splitlines()
    dts = []
    pts = []
    kfs = 0
    timescale = None
    for ln in pkts:
        parts = ln.split(",")
        if len(parts) < 3:
            continue
        pt, dt = int(parts[0]), int(parts[1])
        if "K" in parts[2]:
            kfs += 1
        pts.append(pt)
        dts.append(dt)
    dts_ok = all(dts[i] < dts[i + 1] for i in range(len(dts) - 1))
    timescale = int(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=time_base", "-of", "csv=p=0", str(final)],
        capture_output=True, text=True, check=True).stdout.strip().split("/")[1])
    dpts = [pts[i + 1] - pts[i] for i in range(len(pts) - 1)]
    expected = round(timescale / fps)
    pts_uniform = all(d == expected for d in dpts)

    report = {
        "k": k,
        "loop_duration": loop_dur,
        "T": T,
        "probe": finfo,
        "keyframes": kfs,
        "dts_increasing": bool(dts_ok),
        "pts_uniform": bool(pts_uniform),
        "expected_delta_pts": expected,
        "stderr_clean": bool(stderr_clean),
        "stderr_bad_lines": bad[:20],
    }
    assert dts_ok, "C3: dts не строго возрастает"
    assert pts_uniform, f"C3: Δpts != 1/fps ({expected})"
    assert kfs in (k, k + 1), f"C3: keyframes={kfs}, ожидалось {k}±1"
    assert stderr_clean, f"C4: подозрительные строки в stderr: {bad[:5]}"
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("encode")
    pe.add_argument("frames_dir")
    pe.add_argument("out")
    pe.add_argument("--fps", type=int, default=24)
    pe.add_argument("--overlay-text", default=OVERLAY_TEXT)
    pe.add_argument("--no-overlay", action="store_true")
    pf = sub.add_parser("final")
    pf.add_argument("loop")
    pf.add_argument("track")
    pf.add_argument("final")
    pf.add_argument("--fps", type=int, default=24)
    args = ap.parse_args()

    if args.cmd == "encode":
        n = encode_loop(Path(args.frames_dir), Path(args.out), args.fps,
                        overlay_text=None if args.no_overlay else args.overlay_text)
        print(json.dumps({"encoded_frames": n, "out": str(args.out)}))
        rep = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "seam_check.py"),
             args.out], capture_output=True, text=True)
        print(rep.stdout)
        raise SystemExit(rep.returncode)
    if args.cmd == "final":
        rep = build_final(Path(args.loop), Path(args.track), Path(args.final),
                          fps=args.fps)
        print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
