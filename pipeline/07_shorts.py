#!/usr/bin/env python3
"""Шаг 7: 2 Shorts из long-form последнего run (воронка на длинное видео, DECISIONS п.6-7).

Окна: librosa RMS + onsets по track.mp3 -> 2 непересекающихся окна (40с, минимум 15),
каждое стартует на onset с максимальной средней энергией окна (хук). Нарезка готового
трека/обложки — звук и визуал не меняются (sample gate).
Видео: 1080x1920, blur-фон + обложка по центру, aac, loudnorm I=-14.
Загрузка тем же OAuth; ссылка на long-form из runs/<run>/published.json (пишет 05_publish).
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from common import latest_run_dir

WIN_SEC = 40.0  # цель 30-45с
MIN_SEC = 15.0
HASHTAGS = "#Shorts #lofi #animelofi #studymusic"
AI_NOTE = "AI-generated music and visuals (synthetic content)."


def pick_windows(rms, fps: float, onsets, dur: float) -> list[tuple[float, float]]:
    """2 непересекающихся окна [s, e] внутри трека; старт на onset (иначе сетка 1с)."""
    length = min(WIN_SEC, dur / 2)
    if length < MIN_SEC:
        raise ValueError(f"трек {dur:.0f}с короче {2 * MIN_SEC:.0f}с — Shorts не нарезать")
    cum = np.concatenate([[0.0], np.cumsum(np.asarray(rms, dtype=float))])
    n = int(round(length * fps))

    def score(s):
        i = int(round(s * fps))
        return (cum[min(i + n, len(cum) - 1)] - cum[i]) / n

    grid = [float(s) for s in np.arange(0, dur - length + 1e-9, 1.0)]
    pool = [float(s) for s in onsets if 0 <= s <= dur - length]

    def best(cands, ok=lambda s: True):
        return next((s for s in sorted(cands, key=lambda s: (-score(s), s)) if ok(s)), None)

    first = best(pool) if pool else best(grid)
    free = lambda s: s >= first + length or s + length <= first  # noqa: E731
    second = best(pool, free)
    if second is None:  # все onset'ы перекрывают первое окно — добиваем сеткой
        second = best(grid, free)
    return sorted([(first, first + length), (second, second + length)])


def analyze(track: Path) -> list[tuple[float, float]]:
    import librosa
    y, sr = librosa.load(str(track), sr=22050, mono=True)
    hop = 512
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    onsets = librosa.onset.onset_detect(y=y, sr=sr, hop_length=hop, units="time")
    return pick_windows(rms, sr / hop, onsets, len(y) / sr)


def render(image: Path, track: Path, start: float, end: float, out: Path) -> None:
    # blur-фон считаем один раз в PNG: per-frame boxblur 1080x1920 + x264 на всех ядрах ловил OOM-kill
    frame = out.with_suffix(".png")
    vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:2[bg];"
          "[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(image), "-filter_complex", vf,
                    "-frames:v", "1", str(frame)], check=True)
    dur = f"{end - start:.2f}"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-r", "30", "-i", str(frame),
        "-ss", f"{start:.2f}", "-t", dur, "-i", str(track), "-map", "0:v", "-map", "1:a",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-threads", "4",
        "-c:a", "aac", "-b:a", "192k", "-t", dur, str(out),
    ], check=True)


def short_body(idea: dict, long_url: str, n: int) -> dict:
    title = f"{idea['title'][:80]} pt.{n} #Shorts"
    desc = f"Full mix: {long_url}\n\n{AI_NOTE}\n\n{HASHTAGS}"
    return {
        "snippet": {"title": title[:100], "description": desc, "tags": idea.get("tags", []),
                    "categoryId": "10", "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True},
    }


def main() -> None:
    run_dir = latest_run_dir()
    pub = run_dir / "published.json"
    if not pub.exists():
        print(f"skip: нет {pub} — long-form не опубликован, Shorts без ссылки не грузим")
        return
    long_url = json.loads(pub.read_text(encoding="utf-8"))["url"]
    idea = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))
    image = run_dir / "frame.png" if (run_dir / "frame.png").exists() else run_dir / "cover.png"
    track = run_dir / "track.mp3"

    wins = analyze(track)
    print(f"windows: {wins}")
    outs = []
    for i, (s, e) in enumerate(wins, 1):
        out = run_dir / f"short_{i}.mp4"
        render(image, track, s, e, out)
        outs.append(out)

    from importlib import import_module
    from googleapiclient.http import MediaFileUpload
    from youtube_oauth import check_auth
    if not check_auth(quiet=True):
        sys.exit("ERROR: нет валидного OAuth-токена")
    yt = import_module("05_publish")._get_youtube_service()
    ids = []
    for i, out in enumerate(outs, 1):
        req = yt.videos().insert(part="snippet,status", body=short_body(idea, long_url, i),
                                 media_body=MediaFileUpload(str(out), mimetype="video/mp4", resumable=True))
        resp = None
        while resp is None:
            _, resp = req.next_chunk()
        ids.append(resp["id"])
        print(f"OK: short {i} https://youtube.com/shorts/{resp['id']}")
    (run_dir / "shorts.json").write_text(json.dumps({"ids": ids, "windows": wins}), encoding="utf-8")


if __name__ == "__main__":
    main()
