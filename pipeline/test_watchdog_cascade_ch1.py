#!/usr/bin/env python3
"""M18 (аудит 25.10): канал 1/2 «Economics of Owning» — 3 пустых public-плейлиста
(Small-Town Business Math, Self-Storage & Real Assets, Car Washes & Laundromats).
Каскад M13/M18 обязан идти по ОБОИМ каналам: G1zm0 (YOUTUBE_TOKEN_JSON) и канал 1/2
(YT_CH1_TOKEN_JSON) — без этого пустые плейлисты канал 2 никогда не попадают в каскад."""
import re
from pathlib import Path

WF = Path(__file__).resolve().parent.parent / ".github/workflows/watchdog.yml"


def test_watchdog_cascade_covers_ch1():
    t = WF.read_text()
    m = re.search(r"M13 cascade.*?(?=\n      - name:|\Z)", t, re.S)
    assert m, "шаг M13 cascade не найден в watchdog.yml"
    step = m.group(0)
    assert "YOUTUBE_TOKEN_JSON" in step, "нет базового токена каскада"
    assert "YT_CH1_TOKEN_JSON" in step, "каскад не покрывает канал 1/2 (нет YT_CH1_TOKEN_JSON)"
    assert re.search(r'YOUTUBE_TOKEN_JSON="\$\{YT_CH1_TOKEN_JSON\}" python3 cascade_private\.py', step), \
        "нет второго запуска cascade_private.py с токеном канал 1/2"


if __name__ == "__main__":  # t_110fa85f: CI запускает файл как скрипт
    _fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for _f in _fns:
        _f()
        print("ok", _f.__name__)
    print(f"PASS {len(_fns)} tests")
