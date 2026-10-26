#!/usr/bin/env python3
"""Пул эталонов стиля G1zm0 (t_d53850f6): ротация reference_audio + промпта по дню.

Один фиксированный эталон (ref1 = K/DA Seraphine) делает треки одного вкуса
(вызов владельца «не будет ли всё одинаковым?»). Пул 10 90-с клипов популярных
аниме/игровых OST:

- детерминированный выбор по UTC-дню: pool[day % len(pool)] — соседние дни
  дают разные пары (эталон, промпт);
- фрагмент 90 с вырезается с 90-й секунды (не с 0:00): интро/тема на первых
  секундах — самый узнаваемый (fingerprint-опасный) кусок трека;
- эталон = только стиль-референс генерации, мелодии чужих треков не
  воспроизводятся (cover-режим генератора запрещён, см. FORBIDDEN_TASK_TYPES).
- варианты промпта вращаются по дню (инструменты, темп, тональность): два
  соседних дня не совпадают (len(POOL) и len(PROMPT_VARIANTS) взаимно просты).
"""
import datetime as dt
import json
import subprocess
from pathlib import Path

POOL = [
    ("N7ce_v08QlE", "K/DA ALL OUT Seraphine", "Indie (Passive Music)"),
    ("S0qlFgDvGfw", "K/DA ALL OUT Seraphine", "Rising Star (Passive Music)"),
    ("TK1Ij_-mank", "Joe Hisaishi", "One Summer Day (Spirited Away OST)"),
    ("t6vWDz5NzOY", "Gareth Coker", "Light of Nibel (Ori OST)"),
    ("1rwAvUvvQzQ", "Lena Raine", "Resurrections (Celeste OST)"),
    ("pEg_d2f6myw", "Mitsukiyo", "Unwelcome School (Blue Archive OST)"),
    ("EHGB9mZC4VI", "gacha guild", "An Evening in Liyue (Genshin Impact OST)"),
    ("U00146agWgg", "gacha guild", "An Evening in Mondstadt (Genshin Impact OST)"),
    ("mhE17UIzJf8", "Sorikai", "Genshin Impact Mondstadt Calm OST"),
    ("qS1wrF4XHtc", "Hoyo Studio", "Relaxing Honkai Star Rail Music"),
]
# ponytail: 10 слотов достаточно для суточной ротации; расширять после
# недельного прогона claim-гейта на этом пуле.

REF_LEN_SEC = 90
REF_START_SEC = 90  # не с 0:00: интро трека — самый fingerprint-узнаваемый кусок
REF_DIR = Path(__file__).resolve().parent.parent / ".state" / "refpool"

# Промпт-варианты = семейство ab_1/ab_3 (t_ef393676, вердикт владельца 20.10).
# Одобрены ab_1 (glockenspiel) и ab_3 (celesta); ab_0 (music box) и ab_2 (harp) без
# оценки -> из ротации убраны. BPM/тональность в тексте = РЕАЛЬНЫЕ параметры одобренных
# генераций: ACE-Step берёт темп из поля bpm, а не из текста (замер librosa 21.10: ab_1
# ~86 при bpm=89 и «76 BPM» в тексте, ab_2 ~76 при bpm=75 и «92 BPM»). 03_music теперь
# берёт bpm/key из текста промпта -> вариант воспроизводит одобренный звук.
# 10 и 2 взаимно просты -> пара (эталон, промпт) не повторяется 20 дней.
PROMPT_VARIANTS = [
    # ab_1: seed 9007 -> bpm 89, F major (эталон U00146agWgg); 25.10 владелец: 89 «слишком энергично» -> 70
    "dreamy lofi chillout instrumental, mellow electric piano chords, glockenspiel highlights, "
    "soft brushed drums, warm bassline, gentle swing, polished clean mix, "
    "wide stereo, serene and bright, 70 BPM, F major, no vocals",
    # ab_3: seed 9021 -> bpm 82, D major (эталон qS1wrF4XHtc); 25.10 -> 68
    "dreamy lofi chillout instrumental, glassy synth pads with celesta melody, "
    "light fingerstyle guitar accents, mellow laid back drums, round bass, "
    "polished airy mix, wide stereo, heartwarming, 68 BPM, D major, no vocals",
]


# Offset on claim (t_d53850f6): the day pair is burned, next attempt takes the next one.
OFFSET_FILE = None  # Path; tests override


def bump_offset(n: int = 1) -> None:
    f = OFFSET_FILE or (REF_DIR / "offset.txt")
    f.parent.mkdir(parents=True, exist_ok=True)
    cur = int(f.read_text()) if f.is_file() else 0
    f.write_text(str(cur + n))


def _offset() -> int:
    f = OFFSET_FILE or (REF_DIR / "offset.txt")
    return int(f.read_text()) if f.is_file() else 0


def _day_epoch(now=None) -> int:
    """Сутки как стабильное число (UTC): 0 -> pool[0]/prompt[0], 1 -> следующая пара."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now - dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)).days


def pick(now=None) -> dict:
    """Детерминированная пара (эталон, промпт) на день. 10 и 2 взаимно просты,
    поэтому пары (эталон, промпт) не повторяются 20 дней, а соседние дни
    различаются хотя бы одним компонентом."""
    day = _day_epoch(now) + _offset()
    e = POOL[day % len(POOL)]
    return {
        "day": day,
        "yt_id": e[0],
        "author": e[1],
        "title": e[2],
        "ref_path": str(REF_DIR / ("ref_%s.wav" % e[0])),
        # 10 и 2 взаимно просты: пара (эталон, промпт) не повторяется 20 дней
        "prompt": PROMPT_VARIANTS[day % len(PROMPT_VARIANTS)],
    }


def ensure_ref(entry=None, out_dir=None) -> Path:
    """Скачать/вырезать 90-с эталон, если файла ещё нет (yt-dlp + ffmpeg).
    Кэш в .state/refpool: повторные запуски не качают."""
    entry = entry or pick()
    out_dir = Path(out_dir or REF_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / ("ref_%s.wav" % entry["yt_id"])
    if out.is_file() and out.stat().st_size > 100_000:
        return out
    raw_prefix = out_dir / ("raw_%s" % entry["yt_id"])
    if not list(out_dir.glob(raw_prefix.name + ".*")):
        url = "https://www.youtube.com/watch?v=" + entry["yt_id"]
        subprocess.run(["yt-dlp", "-q", "-f", "bestaudio", "-o", raw_prefix.name + ".%(ext)s", url],
                       check=True, capture_output=True, cwd=str(out_dir))
    raw = next(iter(out_dir.glob(raw_prefix.name + ".*")))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(REF_START_SEC),
                    "-t", str(REF_LEN_SEC), "-i", str(raw), "-ac", "2", "-ar", "48000", str(out)],
                   check=True)
    raw.unlink(missing_ok=True)
    return out


if __name__ == "__main__":
    import sys
    e = pick()
    if "--ensure" in sys.argv:
        ensure_ref(e)
    print(json.dumps(e, ensure_ascii=False))
