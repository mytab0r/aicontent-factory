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


def main() -> None:
    run_dir = latest_run_dir()
    cover = run_dir / "cover.png"
    track = run_dir / "track.mp3"
    frame = run_dir / "frame.png"
    out_path = run_dir / "video.mp4"

    burn_overlay(cover, frame)

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
