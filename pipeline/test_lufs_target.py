"""t_3ce908a7: цель loudnorm и гейт громкости (A15) из одного места.

Plain script, no pytest. RED на старом коде: литералы loudnorm=I=-14 в 4 файлах рендера,
LUFS_TARGET нет в quality_gate. Фикстура: тихий (-30 LUFS) и громкий (~-4 LUFS) клип
после прод-мастера (mastering.master, lofi) обязаны попасть в MIN_I..MAX_I.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import quality_gate as qg  # noqa: E402

# 1) цель внутри гейта
assert qg.MIN_I <= qg.LUFS_TARGET <= qg.MAX_I, (qg.LUFS_TARGET, qg.MIN_I, qg.MAX_I)

# 2) ни один путь рендера не держит свою цель: числовой loudnorm=I=<число> запрещён вне тестов
lit = re.compile(r"loudnorm=I=-?\d")
bad = [f"{p.name}:{n}" for p in sorted(HERE.glob("*.py")) if not p.name.startswith("test_")
       for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if lit.search(line)]
assert bad == [], f"цель громкости захардкожена мимо quality_gate.LUFS_TARGET: {bad}"

# 3) фикстура: громкость после общей цепочки в гейте, сырой клип вне гейта (проверка ловит дрейф)
import mastering  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    for name, vol in (("quiet", 0.02), ("hot", 7.5)):
        raw, out = Path(td) / f"{name}.wav", Path(td) / f"{name}.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency=330:duration=12:sample_rate=48000,volume={vol}", str(raw)], check=True)
        before = mastering.measure(str(raw))["i"]
        assert qg.loud_why(before), f"{name}: сырой клип {before} LUFS уже в гейте — фикстура не проверяет"
        mastering.master(str(raw), str(out), genre="anime lofi")  # t_522ca872: через прод-ветку master()
        got = mastering.measure(str(out))["i"]
        assert qg.loud_why(got) == [], f"{name}: {before} -> {got} LUFS вне {qg.MIN_I}..{qg.MAX_I}"
        print(f"{name}: {before} -> {got} LUFS")
print("test_lufs_target OK")
