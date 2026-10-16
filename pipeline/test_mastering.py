#!/usr/bin/env python3
"""Самопроверка mastering.py (карточка t_c678b8fa).

Цепочка одобрена владельцем 14.10 (сэмплы phonk_*_master); применяется ко всем
трекам. Гейт: I -14±1 LUFS, LRA <= 8 LU, TP <= -1 dBTP.

Запуск: python3 test_mastering.py <path/to/03_music.py>   (нужен ffmpeg)
Аргумент — путь к 03_music.py в рабочем дереве репо.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
MASTERING = HERE / "mastering.py"


def measure(path) -> dict:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                          "-map", "0:a", "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    tail = err[-2000:]
    return {"i": float(re.findall(r"I:\s+(-?[\d.]+) LUFS", tail)[-1]),
            "lra": float(re.findall(r"LRA:\s+(-?[\d.]+) LU", tail)[-1]),
            "tp": float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", tail)[-1])}


# ---- 03_music применяет мастер до записи music_meta.json (после всех веток out_path) ----
if len(sys.argv) > 1:
    msrc = Path(sys.argv[1]).read_text(encoding="utf-8")
    assert "import mastering" in msrc or "from mastering import" in msrc, "нет импорта"
    assert "mastering.master(" in msrc, "03_music не применяет мастеринг"
    assert msrc.index("music_meta.json") > msrc.index("mastering.master("), \
        "мастер должен стоять до записи music_meta.json"


def synth(dst: Path) -> None:
    """Динамичный сигнал: 4с -10dB / 4с -30dB x8 (сырые треки имеют LRA ~13;
    сегменты >=4с, чтобы 3с short-term окна ebur128 не смешивали уровни)."""
    segs = [f"sine=frequency=220:duration=4:sample_rate=48000,volume={'0.316' if i % 2 == 0 else '0.032'}[a{i}]"
            for i in range(8)]
    graph = ";".join(segs) + ";" + "".join(f"[a{i}]" for i in range(8)) + "concat=n=8:v=0:a=1[out]"
    subprocess.run(["ffmpeg", "-hide_banner", "-y", "-loglevel", "error", "-filter_complex", graph,
                    "-map", "[out]", "-c:a", "pcm_s16le", str(dst)], check=True)


def run_master(src: Path, dst: Path) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("mastering", MASTERING)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.master(src, dst)  # Path, как в 03_music (run 38881864243: TypeError Path+str)


with tempfile.TemporaryDirectory() as td:
    raw = Path(td) / "raw.wav"
    synth(raw)
    before = measure(raw)
    assert before["lra"] >= 10, f"тест-сигнал должен быть динамичным, а {before}"

    out = Path(td) / "mastered.mp3"
    a = run_master(raw, out)
    got = measure(out)
    print(f"gate: I={got['i']} LRA={got['lra']} TP={got['tp']} (было I={before['i']} LRA={before['lra']})")
    assert -15 <= got["i"] <= -13 and got["lra"] <= 8 and got["tp"] <= -1, got

    out2 = Path(td) / "mastered2.mp3"
    run_master(out, out2)  # идемпотентность: double loudnorm в час-миксе
    b = measure(out2)
    print(f"double: I={b['i']} LRA={b['lra']} TP={b['tp']}")
    assert -15 <= b["i"] <= -13 and b["lra"] <= 8 and b["tp"] <= -1, b

    # 03_music зовёт master(out_path, out_path): ffmpeg не умеет писать в свой вход
    import shutil
    inplace = Path(td) / "inplace.mp3"
    shutil.copy(out, inplace)
    run_master(inplace, inplace)
    c = measure(inplace)
    assert -15 <= c["i"] <= -13 and c["lra"] <= 8 and c["tp"] <= -1, c

print("test_mastering OK")


# ---- lofi: одобренный 13.10 звук ref1 (LRA ~11) цепочка phonk давила до LRA 1.8 = «каша» (16.10) ----
def run_master_genre(src: Path, dst: Path, genre: str) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("mastering", MASTERING)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.master(src, dst, genre=genre)


with tempfile.TemporaryDirectory() as td:
    raw = Path(td) / "raw.wav"
    synth(raw)
    out = Path(td) / "lofi.mp3"
    run_master_genre(raw, out, "anime lofi")
    got = measure(out)
    print(f"lofi: I={got['i']} LRA={got['lra']} TP={got['tp']}")
    assert -15 <= got["i"] <= -13 and got["tp"] <= -1, got
    assert got["lra"] >= 5, f"lofi-мастер раздавил динамику: {got}"
print("test_mastering lofi OK")
