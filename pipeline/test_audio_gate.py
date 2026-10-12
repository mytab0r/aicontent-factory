#!/usr/bin/env python3
"""Тесты audio_gate.py — детерминированный гейт качества трека перед публикацией.

Критерии (kanban t_44de72aa): одна тональность >=85% 15-с окон, разброс строя
<=0.15 полутона, нет секунд тише -45 dB (кроме финального фейда), true peak
<= -1 dBTP. Проверяем на синтетике: каждая проверка ловит свой дефект.
Запуск: python3 pipeline/test_audio_gate.py (нужны numpy + ffmpeg).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_gate as g  # noqa: E402

SR = g.SR


def chord(root_midi: int, minor: bool, sec: float, cents: float = 0.0) -> np.ndarray:
    t = np.arange(int(sec * SR)) / SR
    third = 3 if minor else 4
    x = np.zeros_like(t)
    for semi, amp in ((0, 1.0), (third, 0.8), (7, 0.8), (12, 0.5), (-12, 0.6)):
        f = 440.0 * 2 ** ((root_midi + semi - 69 + cents / 100) / 12)
        x += amp * np.sin(2 * np.pi * f * t)
    return x


def progression(key_root: int, sec: float, cents: float = 0.0) -> np.ndarray:
    # I-IV-V-I в мажоре: тоника явно доминирует
    parts, i = [], 0
    while sum(len(p) for p in parts) < sec * SR:
        r = (0, 5, 7, 0)[i % 4]
        parts.append(chord(key_root + r, False, 2.0, cents))
        i += 1
    x = np.concatenate(parts)[: int(sec * SR)]
    return 0.2 * x / np.max(np.abs(x))


def test_key_and_tuning_ok():
    x = progression(60, 90)  # C major
    r = g.analyze_pcm(x)
    assert r["key_share"] >= 0.85, r
    assert r["key"] == "C major", r
    assert r["tuning_spread"] <= 0.15, r
    assert r["tuning_share"] >= 0.60, r
    assert r["silent_seconds"] == 0, r


def test_key_change_fails():
    x = np.concatenate([progression(60, 45), progression(66, 45)])  # C -> F#
    r = g.analyze_pcm(x)
    assert r["key_share"] < 0.85, r


def test_tuning_drift_fails():
    x = np.concatenate([progression(60, 45), progression(60, 45, cents=40)])
    r = g.analyze_pcm(x)
    ok = r["tuning_spread"] > 0.15 or r["tuning_share"] < 0.60
    assert ok, r


def test_silence_detected_but_final_fade_ignored():
    x = progression(60, 60)
    x[20 * SR: 23 * SR] = 0.0  # дыра на стыке
    r = g.analyze_pcm(x)
    assert r["silent_seconds"] >= 2, r
    y = progression(60, 60)
    y[-3 * SR:] *= np.linspace(1, 0, 3 * SR)  # фейд в конце — допустим
    assert g.analyze_pcm(y)["silent_seconds"] == 0


def test_check_file_true_peak_and_verdict():
    with tempfile.TemporaryDirectory() as d:
        hot = Path(d) / "hot.wav"
        x = progression(60, 40)
        x = 0.999 * x / np.max(np.abs(x))
        g.write_wav(hot, np.stack([x, x], 1), SR)
        r = g.check_file(hot)
        assert r["true_peak"] > -1.0, r
        assert not r["ok"] and "true_peak" in " ".join(r["fails"]), r


def test_cli_exit_code():
    with tempfile.TemporaryDirectory() as d:
        good = Path(d) / "good.wav"
        x = progression(60, 40)
        g.write_wav(good, np.stack([x, x], 1), SR)
        p = subprocess.run([sys.executable, str(Path(g.__file__)), str(good)], capture_output=True, text=True)
        assert p.returncode == 0, p.stdout + p.stderr


if __name__ == "__main__":
    test_key_and_tuning_ok()
    test_key_change_fails()
    test_tuning_drift_fails()
    test_silence_detected_but_final_fade_ignored()
    test_check_file_true_peak_and_verdict()
    test_cli_exit_code()
    print("all audio_gate tests passed")
