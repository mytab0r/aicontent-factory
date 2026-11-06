"""t_6633f8cd: A18 correction must preserve musical dynamics within each block."""
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import bank_release as br
import mastering
import quality_gate as qg


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


if __name__ == "__main__":
    test_flatten_preserves_lra_and_fixes_jump()
