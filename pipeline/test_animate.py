#!/usr/bin/env python3
"""Self-check анимации: промпт движения из сцены выпуска, число повторов петли под трек."""
import importlib.util
from pathlib import Path

def load(name):
    s = importlib.util.spec_from_file_location(name, Path(__file__).parent / f"{name}.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

an = load("03b_animate")
p = an.motion_prompt({"cover_prompt": "rainy tokyo cafe with pumpkin, aesthetic lofi album art"})
assert "rainy tokyo cafe with pumpkin" in p and "static camera" in p, p
assert an.motion_prompt({}).endswith("static camera")  # нет сцены -> общий промпт, не падаем

asm = load("04_assemble")
assert asm.repeats(6.0, 600.0) == 101  # с запасом: -shortest обрежет по треку
assert asm.repeats(6.0, 5.0) == 2  # +1 цикл запаса всегда
print("OK test_animate")
