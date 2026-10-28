#!/usr/bin/env python3
"""t_3c6b9f04: tempdir критика (w/s000NN.wav, 190-620 MB) удаляется и при успехе, и при сбое критика."""
import subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import quality_gate as qg

base = tempfile.mkdtemp(prefix="qg-tmpclean-")
src = f"{base}/src.wav"
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=70", src], check=True)
tempfile.tempdir = f"{base}/tmp"  # все mkdtemp/TemporaryDirectory модуля попадут сюда
Path(tempfile.tempdir).mkdir()


def left():
    return sorted(p.name for p in Path(tempfile.tempdir).iterdir())


def boom(paths):
    raise RuntimeError("critic crash")


ok = lambda paths: [7.0] * len(paths)
rep = qg.window_report(src, [30.0], critic=ok)
assert rep["wins"] and rep["seams"], rep
assert left() == [], f"успех: tempdir не удалён {left()}"
assert len(qg.ce_windows_batch([src], critic=ok)[0]) >= 1 and left() == [], left()
assert len(qg.ce_batch([src], critic=ok)[0]) == 3 and left() == [], left()
for fn in (lambda: qg.window_report(src, [30.0], critic=boom), lambda: qg.ce_windows_batch([src], critic=boom),
           lambda: qg.ce_batch([src], critic=boom)):
    try:
        fn()
        raise AssertionError("ожидали исключение критика")
    except RuntimeError:
        pass
    assert left() == [], f"сбой: tempdir не удалён {left()}"
why, _ = qg.full_ce_why(src, [30.0], critic=boom)
assert why and why[0].startswith("R5") and left() == [], (why, left())
assert Path(src).exists(), "исходный трек тронут"
subprocess.run(["rm", "-rf", base])
print("OK test_tmp_cleanup")
