#!/usr/bin/env python3
"""V8 (каталог): 720p в ленте выглядит дёшево, HD-ранжирование ниже.
04_assemble рендерит 1920x1080; гейты --final/--video не пропускают короткую сторону < 1080.
Запуск: python3 pipeline/test_v8_resolution.py"""
import importlib.util, inspect, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

if not shutil.which("ffmpeg"):
    print("skip: нет ffmpeg")
    sys.exit(0)

import quality_gate as qg

spec = importlib.util.spec_from_file_location("asm", ROOT / "pipeline" / "04_assemble.py")
asm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(asm)


def _mk(path, size, d=3):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"color=c=gray:s={size}:r=5:d={d}",
                    "-f", "lavfi", "-i", f"sine=f=440:d={d}", "-ac", "2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)


with tempfile.TemporaryDirectory() as td:
    lo, hd, vert = (f"{td}/{n}.mp4" for n in ("lo", "hd", "vert"))
    _mk(lo, "1280x720")
    _mk(hd, "1920x1080")
    _mk(vert, "1080x1920")  # шортсы/owning: вертикаль с короткой стороной 1080 проходит
    assert any("1080" in w for w in qg.res_why(lo)), qg.res_why(lo)
    assert qg.res_why(hd) == [], qg.res_why(hd)
    assert qg.res_why(vert) == [], qg.res_why(vert)
    assert qg.res_why(f"{td}/novideo.mp4") == []  # нет файла/видео-потока — не наша проверка

# прод рендерит 1080p, а не 720p (V8 родился из 720p-релиза p-kkEmLGviU)
assert (asm.TARGET_W, asm.TARGET_H) == (1920, 1080), (asm.TARGET_W, asm.TARGET_H)
# детектор подключен в оба пути заливки: --final (daily-video 04b) и --video (канал 2)
assert "res_why(" in inspect.getsource(qg.video_why), "res_why не в video_why"
assert "res_why(" in inspect.getsource(qg.main), "res_why не в --final ветке main"
print("test_v8_resolution OK")
