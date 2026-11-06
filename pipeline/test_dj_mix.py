# -*- coding: utf-8 -*-
"""t_96de1cc6: DJ-стык сегментов банка (бит-сетка, такты, bass swap) + мастер склейки без TP-фейла 03c.
Фикстуры = реальные сегменты банка ACE-Step (группа 89 BPM F major): a = хвост 70 с, c = начало 70 с.
Запуск: python3 pipeline/test_dj_mix.py (нужен librosa)."""
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, HERE / fn)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


music = _load("music_dj", "03_music.py")
import quality_gate as qg  # noqa: E402
import mastering  # noqa: E402

A, C = str(HERE / "fixtures/bank89F_a.mp3"), str(HERE / "fixtures/bank89F_c.mp3")


def low_db(f, t0, dur):
    import subprocess
    import re
    e = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(t0), "-t", str(dur), "-i", f, "-af",
                        "lowpass=f=150,astats=measure_overall=RMS_level:measure_perchannel=none", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    return float(re.findall(r"RMS level dB:\s*(-?[\d.]+)", e)[-1])


def test_plan_on_bars():
    pe, ns, L, sw = music.dj_plan(A, C)
    bpm = music._downbeats(A, round(music._probe_sec(A) - 60.0, 2), 60.0)[0]
    assert 80 <= bpm <= 98, bpm  # ACE держит 89 (librosa на банке)
    assert sw and abs(L - music.DJ_BARS * 4 * 60 / bpm) < 1e-6, (L, sw)
    assert 0 <= ns <= 4 * 60 / bpm and pe <= music._probe_sec(A)  # вход nxt — первая сильная доля (<= 1 такт)


def test_seam_on_beat_and_bass_swap():
    with tempfile.TemporaryDirectory() as d:
        a, c = shutil.copy(A, d), shutil.copy(C, d)
        out = f"{d}/x.wav"
        starts, seams = music.concat_tracks([a, c], out)
        L = music.dj_plan(a, c)[2]
        # темп через стык не плывёт: межбитовые интервалы в окне перехода ~ равны
        import librosa
        import numpy as np
        y, sr = librosa.load(out, sr=22050, offset=starts[1] - 8, duration=L + 16)
        _, bt = librosa.beat.beat_track(y=y, sr=sr, units="time")
        ibi = np.diff(bt)
        assert len(ibi) > 10 and np.std(ibi) / np.mean(ibi) < 0.08, ibi
        # bass swap: в середине перехода низ не суммируется (две бочки = +3..6 дБ)
        mid = low_db(out, seams[0] - 2, 4)
        assert mid <= max(low_db(out, starts[1] - 6, 4), low_db(out, starts[1] + L + 2, 4)) + 1.5, mid
        rows = [{"t": t, "ce": 9.0, "rms_l": qg.rms_db(out, t - qg.SEAM_HALF, qg.SEAM_HALF),
                 "rms_r": qg.rms_db(out, t, qg.SEAM_HALF)} for t in seams]
        assert qg.seam_why(rows) == [], rows


def test_quiet_intro_bank_seam_r3():
    """t_2be41a12: daily-video 40527578183 FAIL R3 'стык: RMS -16.5 -> -20.4'. Реальная пара банка:
    nxt (mix_01_2) с тихим интро ~10 дБ ниже тела. До #315 разрыв 3.91 дБ, после 0.98."""
    br = _load("bank_release_r3", "bank_release.py")
    with tempfile.TemporaryDirectory() as d:
        ps = [shutil.copy(HERE / f"fixtures/bankR3_{n}.mp3", d) for n in ("prev", "quiet_intro")]
        br._norm_segments([Path(p) for p in ps], log=lambda *a: None)
        music.prep_segments(ps, log=lambda *a: None)
        out = f"{d}/track.mp3"
        _, seams = music.concat_tracks(ps, out)
        br.master_final(out, "anime lofi")
        rows = [{"t": t, "ce": 9.0, "rms_l": qg.rms_db(out, t - qg.SEAM_HALF, qg.SEAM_HALF),
                 "rms_r": qg.rms_db(out, t, qg.SEAM_HALF)} for t in seams]
        assert qg.seam_why(rows) == [], rows
        assert all(abs(r["rms_l"] - r["rms_r"]) <= qg.SEAM_RMS_MAX - 1 for r in rows), rows  # запас 1 дБ


def test_master_final_tp():
    br = _load("bank_release_dj", "bank_release.py")
    with tempfile.TemporaryDirectory() as d:
        a, c = shutil.copy(A, d), shutil.copy(C, d)
        out = f"{d}/track.mp3"
        music.concat_tracks([a, c], out)
        br.master_final(out, "anime lofi")
        m = mastering.measure(out)
        assert m["tp"] <= qg.MAX_TP, m  # 03c FAIL 24.10: TP -0.8; гейт не ослаблен
        assert abs(m["i"] - qg.LUFS_TARGET) <= 1.0, m


def test_master_final_tp_synthetic_peaks():
    """Синтетика с пиками: розовый шум + 20-мс всплески 3 кГц каждые 2 с (TP > -1 до мастера) -> TP <= MAX_TP."""
    import subprocess
    br = _load("bank_release_dj2", "bank_release.py")
    with tempfile.TemporaryDirectory() as d:
        out = f"{d}/track.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.1:d=40:r=48000",
                        "-f", "lavfi", "-i", "aevalsrc='if(lt(mod(t,2),0.02),0.99*sin(2*PI*3000*t),0)':s=48000:d=40",
                        "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0,volume=4dB",
                        "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", out], check=True)
        assert mastering.measure(out)["tp"] > qg.MAX_TP  # фикстура реально с пиками
        br.master_final(out, "anime lofi")
        m = mastering.measure(out)
        assert m["tp"] <= qg.MAX_TP, m


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
