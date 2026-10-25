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

# Shorts-крючок: заголовок != заголовку long-form, без "pt.N", сцена в заголовке, 2 шорта разные
idea = {"title": "Cozy Halloween Bedroom 🎃 Lofi Beats to Study and Relax to", "tags": []}
t1 = sh.short_body(idea, "u", 1)["snippet"]["title"]
t2 = sh.short_body(idea, "u", 2)["snippet"]["title"]
assert "pt." not in t1 and "pt." not in t2, (t1, t2)
assert t1 != t2 and "Cozy Halloween Bedroom" in t1 and "Cozy Halloween Bedroom" in t2, (t1, t2)
assert not t1.startswith(idea["title"][:30]), t1
assert t1.endswith("#Shorts") and len(t1) <= 100 and len(t2) <= 100
assert sh.scene_of("Rainy Night in Tokyo 🌧️ Lofi Beats to Study") == "Rainy Night in Tokyo"
assert sh.scene_of("Midnight Train") == "Midnight Train"
print("test_shorts hooks OK")

# сетевой TimeoutError на next_chunk валил выпуск 13.10 — загрузка обязана ретраить
for f in ("05_publish.py", "07_shorts.py"):
    assert "next_chunk(num_retries=" in (Path(__file__).parent / f).read_text(encoding="utf-8"), f
print("test_shorts upload-retry OK")

# ---- шаг 3 (t_c678b8fa): хэштеги Shorts по жанру ----
def _short_desc_for(title):
    return sh.short_body({"title": title, "tags": []}, "u", 1)["snippet"]["description"]

_d_lofi = _short_desc_for("Rainy Night 🌙 Lofi Beats to Study")
assert "#phonk" not in _d_lofi and "#lofi" in _d_lofi, _d_lofi
_d_phonk = _short_desc_for("Neon Drive 🌃 Phonk Beats to Drift")
assert "#phonk" in _d_phonk and "#lofi" not in _d_phonk, _d_phonk
print("test_shorts genre-hashtags OK")

# ---- V5/M1 (аудит 17.10): хуки шортсов повторялись — «the vibe you need right now» x3 и
# «put this on and forget the world» x3 за 5 дней (8 хуков по crc32 заголовка). Шаблонность = риск
# inauthentic content. Ротация через .state/hook_idx.txt: 2 шорта/день x 14 дней = 28 разных хуков.
import tempfile as _tf
assert len(set(h.lower() for h in sh.HOOKS)) == len(sh.HOOKS) >= 28, len(sh.HOOKS)
with _tf.TemporaryDirectory() as _d:
    _used = [sh.next_hook(Path(_d)) for _ in range(28)]
assert len(set(_used)) == 28, [h for h in _used if _used.count(h) > 1]
assert sh.short_body(idea, "u", 1, hook="x y z")["snippet"]["title"].startswith("x y z | ")
assert "next_hook(" in (Path(__file__).parent / "07_shorts.py").read_text(encoding="utf-8").split("def main")[1]
print("test_shorts hook-rotation OK")
assert "short_why(" in (Path(__file__).parent / "07_shorts.py").read_text(encoding="utf-8").split("def main")[1]
print("test_shorts V3 gate wired OK")

# A24: render накладывает фейды гейта, main проверяет края шортса до заливки
_src = (Path(__file__).parent / "07_shorts.py").read_text(encoding="utf-8")
assert "SHORT_FADES" in _src.split("def render")[1].split("def ")[0], "render без фейдов A24"
assert "short_edge_why(" in _src.split("def main")[1], "main без проверки краёв A24"
