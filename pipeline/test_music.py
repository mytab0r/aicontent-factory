#!/usr/bin/env python3
"""Самопроверка 03_music.py: без scipy, без зависаний, корректный диапазон."""
import importlib.util
import sys
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("music", Path(__file__).parent / "03_music.py")
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)

track = music.generate_track(duration_sec=5, seed=0)
assert len(track) == music.SR * 5, "длина трека не совпадает с запрошенной"
assert not np.isnan(track).any(), "в треке NaN"
assert np.max(np.abs(track)) <= 1.0, "клиппинг: пик громкости выше 1.0"
assert np.max(np.abs(track)) > 0.1, "трек подозрительно тихий — скорее всего ошибка синтеза"

print("OK: generate_track() даёт корректный сигнал без NaN/клиппинга")
