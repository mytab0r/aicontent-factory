"""t_6633f8cd: A18 correction must preserve musical dynamics within each block.
t_619efc27: допуск flatten_blocks не должен быть строже A18-гейта — регресс на tol=1.25.
"""
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import bank_release as br
import mastering
import quality_gate as qg

# Чередование блоков +2.4/-2.4 LU от медианы: легальный контраст (сосед 4.8 > JUMP_MAX лишь
# на границе допуска). tol=1.25 срезал его до LRA 2.6 < 3.5 — прод-сигнатура (runs 41217266580,
# 41222543105: LRA 3.3/3.2 < 3.5). tol=1.75 оставляет 3.7.
ALT = "+".join(f"{10 ** (x / 20):.4f}*between(t,{i * 60},{(i + 1) * 60}-0.001)"
               for i, x in enumerate([0, 2.4, -2.4, 2.4, -2.4, 0]))


def test_flatten_preserves_lra_and_fixes_jump():
    with tempfile.TemporaryDirectory() as td:
        p = str(Path(td) / "track.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "anoisesrc=c=pink:a=0.1:d=360:r=48000:seed=7",
                        "-af", "volume='(1+0.15*sin(2*PI*t/15))*if(lt(t,180),1,0.5)':eval=frame",
                        "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", p], check=True)
        before = mastering.measure(p)
        assert before["lra"] >= qg.REF["lofi"]["min_lra"]
        assert qg.loudjump_why(p), "fixture must reproduce A18"
        br.flatten_blocks(p)
        after = mastering.measure(p)
        print("flatten", before, after, flush=True)
        assert after["lra"] >= qg.REF["lofi"]["min_lra"], after
        assert not qg.loudjump_why(p)
        assert qg.REF["lofi"]["min_lra"] == 3.5


def test_flatten_tol_not_stricter_than_a18_gate():
    """t_619efc27: блоки в ±2.4 LU (легальный контраст) после flatten обязаны дать LRA ≥ min_lra.
    tol=1.25 (старый) загонял их в ±1.25 → LRA 2.6, гейт lofi PASS невозможен по построению."""
    with tempfile.TemporaryDirectory() as td:
        p = str(Path(td) / "alt.mp3")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "anoisesrc=d=360:c=pink:a=0.1:seed=7", "-af", f"volume='{ALT}':eval=frame",
                        "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", p], check=True)
        assert qg.loudjump_why(p), "fixture must reproduce A18"
        br.flatten_blocks(p)
        after = mastering.measure(p)
        print("tol", (qg.JUMP_MAX - 0.5) / 2, after, flush=True)
        assert not qg.loudjump_why(p), qg.loudjump_why(p)
        assert after["lra"] >= qg.REF["lofi"]["min_lra"], after


if __name__ == "__main__":
    test_flatten_preserves_lra_and_fixes_jump()
    test_flatten_tol_not_stricter_than_a18_gate()
