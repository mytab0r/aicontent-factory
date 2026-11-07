# -*- coding: utf-8 -*-
"""t_fdba2de4: _xfade_chain на 20 сегментах (run 40745372322: один ffmpeg-граф на 20 входов -> SIGKILL/OOM
в раннере --memory 4g). Проверяем: успешное завершение, длительность = сумма - 19*d, не больше 2 входов на
вызов ffmpeg, временные файлы удалены, звук = прежний один граф (те же d и кривые qsin)."""
import importlib.util
import os
import re
import subprocess
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("music_xf", Path(__file__).parent / "03_music.py")
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)

N, SEG, D = 20, 6.0, 1.5


def dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                                capture_output=True, text=True, check=True).stdout)


def test_xfade_chain_20_segments():
    with tempfile.TemporaryDirectory() as td:
        segs = []
        for i in range(N):
            p = f"{td}/s{i:02d}.flac"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"sine=f={200 + 20 * i}:r=48000:d={SEG}", "-ac", "2", p], check=True)
            segs.append(p)
        ls = [D] * (N - 1)
        calls, real = [], subprocess.run

        def spy(cmd, *a, **k):
            if cmd and cmd[0] == "ffmpeg":
                calls.append(cmd.count("-i"))
            return real(cmd, *a, **k)
        out = f"{td}/out/mix.flac"
        os.makedirs(os.path.dirname(out))
        subprocess.run = spy
        try:
            music._xfade_chain(segs, ls, out)
        finally:
            subprocess.run = real
        assert max(calls) <= 2, f"граф на {max(calls)} входов: память растёт с числом сегментов"
        assert os.listdir(os.path.dirname(out)) == ["mix.flac"], "временные файлы не удалены"
        exp = N * SEG - (N - 1) * D
        assert abs(dur(out) - exp) < 0.05, (dur(out), exp)
        # эталон = прежний один граф: стыки звучат так же (порог -85 дБ: 1 LSB s16 = -90.3 дБ, округление)
        fc, prev = [], "[0:a]"
        for i in range(1, N):
            o = "[a]" if i == N - 1 else f"[x{i}]"
            fc.append(f"{prev}[{i}:a]acrossfade=d={D:.4f}:c1=qsin:c2=qsin{o}")
            prev = o
        ref = f"{td}/ref.flac"
        real(["ffmpeg", "-y", "-loglevel", "error", *[x for p in segs for x in ("-i", p)],
              "-filter_complex", ";".join(fc), "-map", "[a]", ref], check=True)
        e = real(["ffmpeg", "-hide_banner", "-nostats", "-i", ref, "-i", out, "-filter_complex",
                  "[1:a]aeval=-val(0)|-val(1)[n];[0:a][n]amix=inputs=2:normalize=0,"
                  "astats=measure_overall=Peak_level:measure_perchannel=none", "-f", "null", "-"],
                 capture_output=True, text=True).stderr
        pk = re.findall(r"Peak level dB:\s*(-?[\d.]+|-inf)", e)[-1]
        assert pk == "-inf" or float(pk) < -85, f"разница с прежней склейкой {pk} дБ"


if __name__ == "__main__":
    test_xfade_chain_20_segments()
    print("ok test_xfade_chain_20_segments")
