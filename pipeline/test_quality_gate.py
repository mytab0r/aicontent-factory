#!/usr/bin/env python3
"""Самопроверка quality_gate: раздавленный трек FAIL, живой lofi проходит LRA-гейт; сам мастер lofi проходит гейт."""
import subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import quality_gate as qg, mastering

with tempfile.TemporaryDirectory() as td:
    live = f"{td}/live.wav"   # тихо-громко чередуется -> высокий LRA
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=f=220:d=60,volume='if(lt(mod(t,20),10),1,0.08)':eval=frame", "-ac", "2", live], check=True)
    crushed = f"{td}/crushed.wav"  # та же музыка через жёсткий компрессор = «каша»
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", live, "-af",
                    "acompressor=threshold=0.01:ratio=20:attack=1:release=50,dynaudnorm=f=100:g=3", crushed], check=True)
    w_live, m_live = qg.objective(live, "anime lofi")
    w_cr, m_cr = qg.objective(crushed, "anime lofi")
    print("live", m_live, "crushed", m_cr)
    assert not any("LRA" in w for w in w_live), w_live
    assert any("LRA" in w for w in w_cr), w_cr
    mastered = f"{td}/m.mp3"
    mastering.master(live, mastered, genre="anime lofi")
    w_m, m_m = qg.objective(mastered, "anime lofi")
    assert not any("LRA" in w for w in w_m), f"lofi-мастер сам создаёт кашу: {m_m}"
    assert qg.main(["x", crushed, "anime lofi", "--no-ce"]) == 1
print("test_quality_gate OK")
