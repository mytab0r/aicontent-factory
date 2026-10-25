#!/usr/bin/env python3
"""Шаг 4: собрать видео (обложка + трек) через ffmpeg.

Обязательная маркировка синтетического контента (AGENTS.md п.4): надпись
"AI-generated / synthetic content" вшивается ОДИН РАЗ в саму PNG-обложку
(через PIL), а не per-frame фильтром drawtext — на 1 vCPU drawtext
пересчитывает текст на каждом кадре и видео кодируется со скоростью
~0.15x (120s трек => ~13 минут кодирования). Для статичного кадра это
совершенно не нужно: текст один и тот же все видео.

Длительность видео = длительность трека (без -stream_loop: на этом хосте
флаг у ffmpeg зависает намертво — проверено эмпирически).
"""
import math
import subprocess

from PIL import Image, ImageDraw, ImageOps

from common import latest_run_dir

TARGET_W, TARGET_H = 1280, 720


def burn_overlay(cover_path, out_path) -> None:
    # во весь кадр: масштаб + обрезка по центру (было thumbnail -> чёрные поля по бокам)
    canvas = ImageOps.fit(Image.open(cover_path).convert("RGB"), (TARGET_W, TARGET_H), Image.LANCZOS)

    draw = ImageDraw.Draw(canvas, "RGBA")
    text = "AI-generated / synthetic content"
    pad = 6
    text_w = draw.textlength(text)
    box = (16, TARGET_H - 36, 16 + text_w + pad * 2, TARGET_H - 16)
    draw.rectangle(box, fill=(0, 0, 0, 140))
    draw.text((16 + pad, TARGET_H - 32), text, fill=(255, 255, 255, 160))
    canvas.save(out_path)


def repeats(loop_s: float, track_s: float) -> int:
    return max(1, math.ceil(track_s / loop_s) + 1)


def dur(path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                                check=True).stdout)


def assemble_loop(run_dir, loop, track, out_path) -> None:
    """Петля: перекодируем ОДИН короткий цикл (1280x720 + AI-метка), дальше concat -c copy."""
    seg = run_dir / "loop_720.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(loop), "-vf",
                    "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=24,"
                    "drawbox=x=16:y=684:w=250:h=20:color=black@0.55:t=fill,"
                    "drawtext=text='AI-generated / synthetic content':x=22:y=688:fontsize=13:fontcolor=white@0.7",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-an",
                    str(seg)], check=True)
    lst = run_dir / "loop_list.txt"
    lst.write_text(f"file '{seg.name}'\n" * repeats(dur(seg), dur(track)))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-i", str(track), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)], check=True)


def main() -> None:
    run_dir = latest_run_dir()
    cover = run_dir / "cover.png"
    track = run_dir / "track.mp3"
    frame = run_dir / "frame.png"
    out_path = run_dir / "video.mp4"

    burn_overlay(cover, frame)  # кадр нужен и Shorts/миниатюре
    loop = run_dir / "loop.mp4"
    if loop.exists():
        try:
            assemble_loop(run_dir, loop, track, out_path)
            print(f"video (анимация) -> {out_path}")
            return
        except subprocess.CalledProcessError as e:
            print(f"петля не собралась, статичный кадр: {e}")

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-r", "5", "-i", str(frame),
        "-i", str(track),
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    print(f"video -> {out_path}")


if __name__ == "__main__":
    main()
