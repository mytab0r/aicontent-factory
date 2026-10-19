#!/usr/bin/env python3
"""Шаг 7: 2 Shorts из long-form последнего run (воронка на длинное видео, DECISIONS п.6-7).

Окна: librosa RMS + onsets по track.mp3 -> 2 непересекающихся окна (40с, минимум 15),
каждое стартует на onset с максимальной средней энергией окна (хук). Нарезка готового
трека/обложки — звук и визуал не меняются (sample gate).
Видео: 1080x1920, blur-фон + обложка по центру, aac, loudnorm I=-14.
Загрузка тем же OAuth; ссылка на long-form из runs/<run>/published.json (пишет 05_publish).
"""
import json
import re
import subprocess
import zlib
import sys
from pathlib import Path

import numpy as np

from common import STATE_DIR, latest_run_dir, rotate

WIN_SEC = 40.0  # цель 30-45с
MIN_SEC = 15.0
# Хэштеги по жанру (t_c678b8fa шаг 3): жанр определяется по слову в заголовке
# long-form (тот же маркер, что в guard: watchdog.GENRE_IN_TITLE).
GENRE_HASHTAGS = {
    "phonk": "#Shorts #phonk #wavephonk #driftphonk",
    "lofi": "#Shorts #lofi #animelofi #studymusic",
}


def hashtags_for(title: str) -> str:
    low = (title or "").lower()
    return GENRE_HASHTAGS["phonk"] if "phonk" in low else GENRE_HASHTAGS["lofi"]


AI_NOTE = "AI-generated music and visuals (synthetic content)."
# RESEARCH 13.10: у лидеров Shorts = крючок/ситуация, не "<long title> pt.N"; наши pt.1/pt.2 = 8-55 просм.
HOOKS = [
    "POV: it's 2am and you still have to study",
    "this is your sign to take a break",
    "the song that plays when you finally relax",
    "study with me for 40 seconds",
    "close your eyes and breathe for a moment",
    "the vibe you need right now",
    "put this on and forget the world",
    "when the room is quiet and the tea is warm",
    "POV: rain on the window, deadline tomorrow",
    "save this for your next study session",
    "the calm before the exam",
    "one more chapter, then sleep",
    "POV: you finally cleaned your desk",
    "headphones on, world off",
    "late night, warm lamp, soft beats",
    "your brain on a quiet sunday",
    "this sound feels like a warm blanket",
    "when you need 40 seconds of peace",
    "POV: the city sleeps and you don't",
    "for the ones still awake at 3am",
    "slow down, you're doing fine",
    "the background music of your focus era",
    "coffee is cold but the vibe is warm",
    "POV: first snow outside your window",
    "breathe in, breathe out, keep going",
    "the playlist that never judges you",
    "this is what calm sounds like",
    "a little break for your tired mind",
    "POV: you open the window at midnight",
    "music for the long walk home",
]


def scene_of(title: str) -> str:
    """Сцена из заголовка long-form: всё до первого эмодзи/'|'/' Lofi'."""
    return re.split(r"[^\w\s',&.-]|\s+lofi\b|\s+lo-fi\b", title, maxsplit=1, flags=re.I)[0].strip()


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


def next_hook(state_dir: Path | None = None) -> str:
    """V5/M1: следующий крючок по кругу (.state/hook_idx.txt, коммитится CI): 30 хуков / 2 в день = без повтора 15 дней."""
    return HOOKS[rotate("hook", len(HOOKS), state_dir or STATE_DIR)]


def short_body(idea: dict, long_url: str, n: int, hook: str | None = None) -> dict:
    # ponytail: 30 фиксированных крючков по кругу; LLM-крючки — если CTR Shorts не вырастет
    hook = hook or HOOKS[(zlib.crc32(idea["title"].encode()) + n - 1) % len(HOOKS)]
    title = f"{hook} | {scene_of(idea['title'])[:45]} #Shorts"
    desc = f"Full mix: {long_url}\n\n{AI_NOTE}\n\n{hashtags_for(idea['title'])}"
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
        from quality_gate import short_why  # V3: формат проверяется до заливки, брак не грузим
        why = short_why(out)
        if why:
            sys.exit("ERROR: шортс не прошёл гейт: " + "; ".join(why))
        outs.append(out)

    from importlib import import_module
    from googleapiclient.http import MediaFileUpload
    from youtube_oauth import check_auth
    if not check_auth(quiet=True):
        sys.exit("ERROR: нет валидного OAuth-токена")
    yt = import_module("05_publish")._get_youtube_service()
    ids = []
    for i, out in enumerate(outs, 1):
        req = yt.videos().insert(part="snippet,status", body=short_body(idea, long_url, i, hook=next_hook()),
                                 media_body=MediaFileUpload(str(out), mimetype="video/mp4", resumable=True))
        resp = None
        while resp is None:
            _, resp = req.next_chunk(num_retries=5)
        ids.append(resp["id"])
        print(f"OK: short {i} https://youtube.com/shorts/{resp['id']}")
    (run_dir / "shorts.json").write_text(json.dumps({"ids": ids, "windows": wins}), encoding="utf-8")


if __name__ == "__main__":
    main()
