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
import re
import subprocess

from PIL import Image, ImageDraw, ImageOps

from common import latest_run_dir
from quality_gate import LUFS_TARGET, MAX_TP

TARGET_W, TARGET_H = 1920, 1080  # V8: 720p в нише = «дёшево», HD-ранжирование ниже


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


def normalize(track, dst) -> None:
    """t_c68d7f9c: loudnorm трека ДО mux (TP -2 dBTP, запас под AAC); WAV — без второго lossy-прохода MP3.
    лимитер в mux остаётся страховкой от пиков перекодирования."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(track),
                    "-af", f"loudnorm=I={LUFS_TARGET:g}:TP=-2:LRA=8,aresample=48000",
                    "-c:a", "pcm_s16le", str(dst)], check=True)


TP_TARGET = MAX_TP - 0.3  # запас под округление гейта 04b


def tp_of(path) -> float:
    e = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-i", str(path), "-vn",
                        "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float(re.findall(r"Peak:\s+(-?[\d.]+|-inf)", e)[-1].replace("-inf", "-200"))


def encode_audio(src, dst, tries=5) -> float:
    """t_fef617d9: AAC-кодер ffmpeg (192k) поднимает true peak на несколько дБ ПОСЛЕ лимитера
    (run 40408005493: track TP -1.4 -> video.mp4 +6.5). Лимитер до кодера овершут не видит, поэтому
    меряем ЗАКОДИРОВАННЫЙ звук и опускаем потолок лимитера, пока TP <= TP_TARGET; mux потом -c:a copy.
    320k: овершут кодера меньше (замер: -3.2 dBTP wav -> +1.3 при 192k, -2.6 при 320k). Не сошлось = исключение."""
    limit, tp = -1.5, None
    for _ in range(tries):
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(src),
                        "-af", f"alimiter=limit={limit:.2f}dB:level=false",
                        "-c:a", "aac", "-b:a", "320k", str(dst)], check=True)
        tp = tp_of(dst)
        if tp <= TP_TARGET:
            return tp
        limit -= tp - TP_TARGET + 0.5
    raise RuntimeError(f"AAC true peak {tp:+.1f} dBTP > {TP_TARGET} после {tries} проходов")


def assemble_loop(run_dir, loop, track, out_path) -> None:
    """Петля: перекодируем ОДИН короткий цикл (TARGET 1920x1080 + AI-метка), дальше concat -c copy."""
    seg = run_dir / "loop_1080.mp4"
    vf = (f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,crop={TARGET_W}:{TARGET_H},fps=24,"
          f"drawbox=x=16:y={TARGET_H - 36}:w=250:h=20:color=black@0.55:t=fill,"
          f"drawtext=text='AI-generated / synthetic content':x=22:y={TARGET_H - 32}:fontsize=13:fontcolor=white@0.7")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(loop), "-vf", vf,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-an",
                    str(seg)], check=True)
    lst = run_dir / "loop_list.txt"
    lst.write_text(f"file '{seg.name}'\n" * repeats(dur(seg), dur(track)))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-i", str(track), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "copy", "-shortest", str(out_path)], check=True)


def main() -> None:
    run_dir = latest_run_dir()
    cover = run_dir / "cover.png"
    track = run_dir / "track.mp3"
    frame = run_dir / "frame.png"
    out_path = run_dir / "video.mp4"

    burn_overlay(cover, frame)  # кадр нужен и Shorts/миниатюре
    track_norm = run_dir / "track_norm.wav"
    normalize(track, track_norm)
    track = run_dir / "track_final.m4a"  # оба пути муксят готовый AAC без перекодирования (-c:a copy)
    print(f"AAC true peak {encode_audio(track_norm, track):+.1f} dBTP")
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
        "-c:a", "copy",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    print(f"video -> {out_path}")


if __name__ == "__main__":
    main()
