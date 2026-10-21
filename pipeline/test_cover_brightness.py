#!/usr/bin/env python3
"""V9 (каталог): обложка слишком тёмная/пересвеченная для миниатюры (YAVG < 30 или > 220 из 255) = FAIL в 04b.
Самая тёмная миниатюра канала (YAVG 28.9, замер 21.10) проходит; чёрная (16) и белая (235) — брак."""
import subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import quality_gate as qg

with tempfile.TemporaryDirectory() as td:
    res = {}
    for name, c in (("night", "0x292929"), ("mid", "0x585858"), ("darkest", "0x0E0E0E"), ("black", "0x000000"), ("white", "0xFFFFFF")):
        p = f"{td}/{name}.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c={c}:s=64x64:d=1",
                        "-frames:v", "1", p], check=True)
        res[name] = qg.cover_why(p)
    assert res["night"] == res["mid"] == res["darkest"] == [], res
    assert any("тёмная" in w for w in res["black"]), res
    assert any("пересвечена" in w for w in res["white"]), res
    assert qg.COVER_YMIN == 24 and qg.COVER_YMAX == 220
    assert qg.cover_why(f"{td}/missing.png") == []  # обложки нет -> проверяет integrity, не этот детектор
print("test_cover_brightness OK")
