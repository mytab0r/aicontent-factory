#!/usr/bin/env python3
"""Гейт качества трека (audio_gate.py) на синтетике: одна тональность проходит,
смена тональности / сдвиг строя / дыра тишины / пик -- проваливают."""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_gate as g

SR = 22050


def chord(root_hz, sec, cents=0.0):
    """Каденция I-IV-V-I по 2 с: однозначно задаёт мажорный звукоряд от root."""
    t = np.arange(2 * SR) / SR
    f = root_hz * 2 ** (cents / 1200)
    bar = np.concatenate([sum(np.sin(2 * np.pi * f * 2 ** ((r + s) / 12) * t) for s in (0, 4, 7)) / 6
                          for r in (0, 5, 7, 0)])
    return np.tile(bar, int(np.ceil(sec / 8)))[:int(sec * SR)]


def wav(y):
    p = tempfile.mktemp(suffix=".wav")
    raw = (np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "1",
                    "-i", "-", p], input=raw, check=True)
    return p


C4, FS4 = 261.63, 369.99
m_ok = g.measure(wav(chord(C4, 120)))
assert m_ok["key"] == "C" and m_ok["key_share"] == 1.0, m_ok
assert m_ok["silent_sec"] == 0 and m_ok["tuning_spread"] <= 0.15, m_ok
assert g.check(m_ok) == [], g.check(m_ok)

# A min = звукоряд C maj: не считается сменой тональности
assert g.key_of(np.roll(g._MIN, 9)) == "C"

m_key = g.measure(wav(np.concatenate([chord(C4, 60), chord(FS4, 60)])))
assert m_key["key_share"] < 0.85 and any("тональность" in f for f in g.check(m_key)), m_key

m_tune = g.measure(wav(np.concatenate([chord(C4, 60), chord(C4, 60, cents=40)])))
assert m_tune["tuning_spread"] > 0.15 and any("строя" in f for f in g.check(m_tune)), m_tune

m_gap = g.measure(wav(np.concatenate([chord(C4, 60), np.zeros(3 * SR), chord(C4, 60)])))
assert m_gap["silent_sec"] >= 3 and any("тише" in f for f in g.check(m_gap)), m_gap

assert any("peak" in f for f in g.check({**m_ok, "true_peak": -0.2}))
print("OK audio_gate")

# внутренняя тишина ловится, края (их режет сшивка) нет
tone = 0.3 * np.sin(2 * np.pi * 440 * np.arange(60 * g.SR) / g.SR).astype("float32")
e = tone.copy(); e[:5 * g.SR] = 0; e[-5 * g.SR:] = 0
assert g.inner_silent_sec(e) == 0
m = tone.copy(); m[30 * g.SR:34 * g.SR] = 0
assert g.inner_silent_sec(m) == 4, g.inner_silent_sec(m)
print("OK inner_silence")
