#!/usr/bin/env python3
"""Гейт качества трека перед публикацией (карточка t_44de72aa, аудит 4HB26c4yow0).

Приёмка: одна тональность >= 85% 15-с окон, разброс строя <= 0.15 полутона,
ни одной секунды тише -45 dB, true peak <= -1 dBTP.
Тональность: Крумхансл по chroma; параллельные мажор/минор (A maj = F# min) = один звукоряд,
анализатор их путает, на слух это не смена тональности.

    python3 audio_gate.py track.mp3 [--json gate.json]   # exit 1 = провал
"""
import json
import re
import subprocess
import sys
from collections import Counter

import numpy as np

KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.6, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
LIMITS = {"key_share": 0.85, "tuning_spread": 0.15, "silent_sec": 0, "true_peak": -1.0}
SR = 22050


def key_of(chroma_mean) -> str:
    """Звукоряд по мажорной тонике: минор -> его параллельный мажор (A min -> 'C')."""
    best = max([(np.corrcoef(np.roll(_MAJ, i), chroma_mean)[0, 1], i) for i in range(12)]
               + [(np.corrcoef(np.roll(_MIN, i), chroma_mean)[0, 1], (i + 3) % 12) for i in range(12)])
    return KEYS[best[1]]


def true_peak(path) -> float:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                          "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float(re.findall(r"Peak:\s+(-?[\d.]+|-inf)", err)[-1].replace("-inf", "-200"))


def measure(path, win=15, tune_win=60) -> dict:
    import librosa
    y, sr = librosa.load(str(path), sr=SR, mono=True)
    hop = 2048
    chroma = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=hop, tuning=0.0)
    fpw = int(win * sr / hop)
    keys = [key_of(chroma[:, i:i + fpw].mean(1)) for i in range(0, chroma.shape[1] - fpw + 1, fpw)]
    top, cnt = Counter(keys).most_common(1)[0]
    n = len(y) // sr
    db = 20 * np.log10(np.sqrt((y[:n * sr].reshape(n, sr) ** 2).mean(1)) + 1e-9)
    tun = [float(librosa.estimate_tuning(y=y[s:s + tune_win * sr], sr=sr))
           for s in range(0, max(1, len(y) - tune_win * sr // 2), tune_win * sr)]
    return {"key": top, "key_share": round(cnt / len(keys), 3), "keys": dict(Counter(keys)),
            "tuning": [round(t, 2) for t in tun], "tuning_spread": round(max(tun) - min(tun), 3),
            "silent_sec": int((db < -45).sum()), "true_peak": true_peak(path), "duration": n}


def check(m: dict) -> list[str]:
    fails = []
    if m["key_share"] < LIMITS["key_share"]:
        fails.append(f"тональность {m['key']} только {m['key_share']:.0%} окон (<85%)")
    if m["tuning_spread"] > LIMITS["tuning_spread"]:
        fails.append(f"разброс строя {m['tuning_spread']:.2f} пт (>0.15)")
    if m["silent_sec"] > LIMITS["silent_sec"]:
        fails.append(f"{m['silent_sec']} с тише -45 dB")
    if m["true_peak"] > LIMITS["true_peak"]:
        fails.append(f"true peak {m['true_peak']:.1f} dBTP (>-1)")
    return fails


if __name__ == "__main__":
    m = measure(sys.argv[1])
    m["fails"] = check(m)
    if "--json" in sys.argv:
        open(sys.argv[sys.argv.index("--json") + 1], "w").write(json.dumps(m, ensure_ascii=False, indent=2))
    print(json.dumps(m, ensure_ascii=False))
    print("GATE " + ("FAIL: " + "; ".join(m["fails"]) if m["fails"] else "OK"))
    sys.exit(1 if m["fails"] else 0)
