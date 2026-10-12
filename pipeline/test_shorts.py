#!/usr/bin/env python3
"""Self-check 07_shorts.py: окна 15-45с, без пересечений, внутри трека, старт на громком onset;
метаданные Shorts (#Shorts, ссылка на long-form, AI-disclosure). Только numpy, без librosa/ffmpeg."""
import importlib.util
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("shorts", Path(__file__).parent / "07_shorts.py")
sh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sh)

FPS = 10  # кадров RMS в секунду
dur = 180.0
t = np.arange(int(dur * FPS)) / FPS
rms = np.full(t.size, 0.1)
rms[(t >= 40) & (t < 85)] = 1.0    # громкий кусок №1
rms[(t >= 120) & (t < 165)] = 0.8  # громкий кусок №2
onsets = np.array([5, 20, 40, 60, 100, 120, 150, 170.0])

wins = sh.pick_windows(rms, FPS, onsets, dur)
assert len(wins) == 2, wins
for s, e in wins:
    assert 15 <= e - s <= 45, (s, e)
    assert 0 <= s and e <= dur, (s, e)
    assert s in onsets, f"окно должно начинаться на onset: {s}"
(a0, a1), (b0, b1) = sorted(wins)
assert a1 <= b0, f"пересечение {wins}"
assert sorted(wins) == [(40.0, 80.0), (120.0, 160.0)], wins  # хук = громкие onset'ы

# без onset'ов и на коротком треке — всё равно валидные окна
w2 = sh.pick_windows(np.ones(400), FPS, np.array([]), 40.0)
assert len(w2) == 2 and all(15 <= e - s <= 45 and 0 <= s and e <= 40.0 for s, e in w2), w2
(a0, a1), (b0, b1) = sorted(w2)
assert a1 <= b0, w2

# onset'ы есть, но все рядом — второе окно добирается сеткой без пересечения
w3 = sorted(sh.pick_windows(rms, FPS, np.array([40.0, 41.0, 42.0]), dur))
assert w3[0][1] <= w3[1][0] and all(e <= dur for _, e in w3), w3

try:
    sh.pick_windows(np.ones(200), FPS, np.array([]), 20.0)
    raise AssertionError("трек <30с должен падать")
except ValueError:
    pass

body = sh.short_body({"title": "Rainy Night Study", "tags": ["lofi"]}, "https://www.youtube.com/watch?v=abc", 1)
sn = body["snippet"]
assert "#Shorts" in sn["title"] and len(sn["title"]) <= 100, sn["title"]
assert "https://www.youtube.com/watch?v=abc" in sn["description"]
assert "AI-generated" in sn["description"] and "#lofi" in sn["description"]
assert sn["defaultLanguage"] == sn["defaultAudioLanguage"] == "en"
assert body["status"]["containsSyntheticMedia"] is True
print("test_shorts OK")
