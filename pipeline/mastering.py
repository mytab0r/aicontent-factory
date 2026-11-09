"""Мастеринг трека: одобренная владельцем цепочка (14.10, сэмплы phonk_*_master)
+ гейт итогового файла: I -14±1 LUFS, LRA <= 8 LU, TP <= -3 dBTP.

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

from quality_gate import LUFS_TARGET


def measure(path: str) -> dict:
    """I/LRA/TP одним прогоном ebur128=peak=true."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
                          "-map", "0:a", "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    tail = err[-2000:]
    return {"i": float(re.findall(r"I:\s+(-?[\d.]+) LUFS", tail)[-1]),
            "lra": float(re.findall(r"LRA:\s+(-?[\d.]+) LU", tail)[-1]),
            "tp": float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", tail)[-1])}


# t_522ca872 / t_619efc27: в lofi-ветке динамический loudnorm запрещён — давит LRA до «каши»
# (замер 25.10: LRA 19.3 -> 1.6; 1ced2254 вернул LOFI_AF loudnorm -> CI RED на test_master_lra).
# Громкость = статический volume + alimiter; I-undershoot добирает статический gain ниже.
# t_9944c9ce: адаптивный лимитер вместо фиксированного -6 dBFS, чтобы не давить LRA на треках,
# где нужен только небольшой TP-доворот. Итеративно опускаем потолок до TP <= -4 (запас под AAC +2..3 dBTP).
LOFI_TP_TARGET = -4.0  # цель TP на MP3 перед AAC кодированием (04_assemble поднимет до <= -3)


EQ_MAX_DB = 6.0
EQ_PASSES = 2


def eq_gains(measured, ref, cap=EQ_MAX_DB):
    """t_ffa7ff01: дБ на полосу = (эталон - замер) относительно баса 60-150, минус среднее, в ±cap.
    Среднее вычитается: общую громкость ведёт loudnorm, EQ правит только тон."""
    d = [(r - ref[1]) - (m - measured[1]) for m, r in zip(measured, ref)]
    mean = sum(d) / len(d)
    return [max(-cap, min(cap, x - mean)) for x in d]


def eq_af(gains):
    """equalizer на полосу гейта: центр = геом. среднее, ширина = log2(hi/lo) октав."""
    import math
    from quality_gate import BANDS
    return ",".join(f"equalizer=f={math.sqrt(lo * hi):.0f}:t=o:w={math.log2(hi / lo):.2f}:g={g:.2f}"
                    for (lo, hi), g in zip(BANDS, gains))


def master(src: str, dst: str, genre: str = "chill phonk") -> dict:
    phonk = "phonk" in genre
    # t_ffa7ff01 / 20.10 (39370096994): сегменты тянут полосы в разные стороны у ОБОИХ жанров —
    # статичная цепочка phonk дала 0/15 прошедших гейт (ср. |откл| 5.2 дБ в 20-60 и 150-400 Гц).
    # Мерим полосы и тянем к REF жанра; для phonk EQ идёт ПОСЛЕ одобренной цепочки — до неё
    # цепочка сносит тон обратно (тест: phonk adaptive EQ).
    from quality_gate import REF, bands

    PHONK_AF = ("highpass=f=28,bass=g=3:f=55,equalizer=f=300:t=q:w=1.2:g=-2,"
                "treble=g=2:f=10000,"
                "acompressor=threshold=-18dB:ratio=2.5:attack=20:release=250:makeup=2,"
                "extrastereo=m=1.2,"
                f"loudnorm=I={LUFS_TARGET:g}:TP=-4:LRA=8,"
                "aresample=48000,"
                "acompressor=threshold=-18dB:ratio=4:attack=10:release=150:makeup=1.5,"
                "acompressor=threshold=-15dB:ratio=6:attack=5:release=100:makeup=2,"
                "alimiter=limit=0.79:level=disabled,"
                f"loudnorm=I={LUFS_TARGET:g}:TP=-3:LRA=8")

    def run(s: str, d: str, chain: str) -> None:
        # пишем во временный файл: ffmpeg не может писать в свой же вход (src == dst)
        tmp = f"{d}.tmp.mp3"  # d бывает Path (03_music)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", s, "-af", chain,
                        "-c:a", "libmp3lame", "-b:a", "192k", tmp], check=True)
        os.replace(tmp, d)

    if phonk:
        run(src, dst, PHONK_AF)  # одобренная владельцем 14.10 динамика/лимитер
        # повторные проходы ПОСЛЕ цепочки: только тон+громкость, цепочку не повторять (снесёт тон)
        for _ in range(EQ_PASSES):
            run(dst, dst, f"{eq_af(eq_gains(bands(dst), REF['phonk']['bands']))},loudnorm=I={LUFS_TARGET:g}:TP=-4:LRA=8")
    else:
        # t_522ca872: lofi громкость БЕЗ loudnorm (динамический давит LRA -> «каша»).
        m0 = measure(src)
        already = -15 <= m0["i"] <= -13 and m0["tp"] <= -3
        if not already:
            s = src
            for _ in range(EQ_PASSES):
                run(s, dst, f"highpass=f=28,{eq_af(eq_gains(bands(s), REF['lofi']['bands']))}")
                s = dst
        # lofi-volume retry: адаптивный alimiter (t_9944c9ce: итеративно опускаем потолок до TP <= LOFI_TP_TARGET).
        # Старт с консервативным -6 dBFS (limit=0.5) чтобы не давить LRA; уже если TP > target.
        m = measure(dst)
        if not (-15 <= m["i"] <= -13 and m["tp"] <= LOFI_TP_TARGET):
            limit = 0.5  # -6 dBFS linear scale
            for _ in range(5):
                run(dst, dst, f"volume={LUFS_TARGET - m['i']:.2f}dB,alimiter=limit={limit:.2f}:level=disabled:attack=0.1:release=20:asc=0")
                m = measure(dst)
                if -15 <= m["i"] <= -13 and m["tp"] <= LOFI_TP_TARGET:
                    break
                # TP всё ещё выше цели -> ужечаем лимит (линейная шкала: -3 dBTP = 0.71, -4 dBTP = 0.63)
                limit *= 10 ** ((LOFI_TP_TARGET - m["tp"]) / 20) * 0.9
    m = measure(dst)
    # ponytail: догон громкости не сошёлся — ещё до 2 повторов:
    # phonk = одобренный loudnorm-rerun, lofi = адаптивный volume+лимитер (t_9944c9ce).
    for _ in range(2):
        if -15 <= m["i"] <= -13 and (m["lra"] <= 8 or not phonk) and m["tp"] <= LOFI_TP_TARGET:
            break
        af = (f"loudnorm=I={LUFS_TARGET:g}:TP=-4:LRA=8" if phonk
              else f"volume={LUFS_TARGET - m['i']:.2f}dB,alimiter=limit=0.5:level=disabled:attack=0.1:release=20:asc=0")
        run(dst, dst, af)
        m = measure(dst)
    # t_619efc27: динамический loudnorm на экстремальной динамике (длинные паузы) не
    # дотягивает до цели (замер: I -15.7 при I=-14, 5 проходов сходятся туда же) —
    # добираем статическим gain + лимитер, как в bank_release._norm_segments.
    for _ in range(3):
        if -15 <= m["i"] <= -13:
            break
        run(dst, dst, f"volume={LUFS_TARGET - m['i']:+.2f}dB,alimiter=limit=0.5:level=disabled:attack=0.1:release=20:asc=0")
        m = measure(dst)
    assert -15 <= m["i"] <= -13, f"гейт I: {m}"
    assert m["lra"] <= 8 or not phonk, f"гейт LRA: {m}"
    tp_limit = LOFI_TP_TARGET if not phonk else -3
    assert m["tp"] <= tp_limit, f"гейт TP: {m}"
    return m


if __name__ == "__main__":
    print(master(sys.argv[1], sys.argv[2]))
