"""Мастеринг трека: одобренная владельцем цепочка (14.10, сэмплы phonk_*_master)
+ гейт итогового файла: I -14±1 LUFS, LRA <= 8 LU, TP <= -1 dBTP.

Схема: тональная EQ/комп (как в A/B) -> loudnorm (динамический, приводит к
громкости платформы) -> доуплотнение динамики (2 компа: LRA после loudnorm
может оставаться > 8 при больших паузах/тихих секциях) -> safety-limiter ->
финальный loudnorm (возвращает I в гейт после компрессоров).

Запуск: python3 mastering.py <in.mp3> <out.mp3>
"""
import os
import re
import subprocess
import sys


def measure(path: str) -> dict:
    """I/LRA/TP одним прогоном ebur128=peak=true."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
                          "-map", "0:a", "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    tail = err[-2000:]
    return {"i": float(re.findall(r"I:\s+(-?[\d.]+) LUFS", tail)[-1]),
            "lra": float(re.findall(r"LRA:\s+(-?[\d.]+) LU", tail)[-1]),
            "tp": float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", tail)[-1])}


# lofi (одобрен 13.10 по ref1, LRA ~11): только громкость платформы, без EQ/компрессоров.
# Цепочка ниже одобрена для phonk (14.10); на lofi она давила LRA 10.9 -> 1.8 («каша», 16.10).
LOFI_AF = "highpass=f=28,loudnorm=I=-14:TP=-2:LRA=11"


def master(src: str, dst: str, genre: str = "chill phonk") -> dict:
    phonk = "phonk" in genre
    af = LOFI_AF if not phonk else ("highpass=f=28,bass=g=3:f=55,equalizer=f=300:t=q:w=1.2:g=-2,"
          "treble=g=2:f=10000,"
          "acompressor=threshold=-18dB:ratio=2.5:attack=20:release=250:makeup=2,"
          "extrastereo=m=1.2,"
          "loudnorm=I=-14:TP=-2:LRA=8,"
          "aresample=48000,"
          "acompressor=threshold=-18dB:ratio=4:attack=10:release=150:makeup=1.5,"
          "acompressor=threshold=-15dB:ratio=6:attack=5:release=100:makeup=2,"
          "alimiter=limit=0.79:level=disabled,"
          "loudnorm=I=-14:TP=-2:LRA=8")
    def run(s: str, d: str) -> None:
        # пишем во временный файл: ffmpeg не может писать в свой же вход (src == dst)
        tmp = f"{d}.tmp.mp3"  # d бывает Path (03_music)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", s, "-af", af,
                        "-c:a", "libmp3lame", "-b:a", "192k", tmp], check=True)
        os.replace(tmp, d)

    run(src, dst)
    m = measure(dst)
    # ponytail: экстремальная динамика (длинные паузы) ломает LRA одним проходом —
    # повторные полные проходы сходятся (LRA 15.6->6.5->2.5); 3 прохода, дальше гейт.
    for _ in range(2):
        if -15 <= m["i"] <= -13 and (m["lra"] <= 8 or not phonk) and m["tp"] <= -1:
            break
        run(dst, dst)
        m = measure(dst)
    assert -15 <= m["i"] <= -13, f"гейт I: {m}"
    assert m["lra"] <= 8 or not phonk, f"гейт LRA: {m}"
    assert m["tp"] <= -1, f"гейт TP: {m}"
    return m


if __name__ == "__main__":
    print(master(sys.argv[1], sys.argv[2]))
