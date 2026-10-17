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

# Жалоба владельца 17.10 (phonk p-kkEmLGviU, отрезок 300-420 с с YouTube): мелодия 1-5 кГц на 2-3 дБ тише,
# 150-400 Гц на 2 дБ громче одобренного v2. Старый гейт (5 полос ±3 дБ) это пропустил — новый обязан отклонить.
PUB = [-23.8, -23.0, -29.3, -26.8, -32.6, -36.3, -34.2, -35.8]
why = qg.judge(PUB, 1.0, "phonk")
assert any("баланс" in w for w in why), why
assert any("2500-5000" in w for w in why), why
# эталоны (полный файл, абсолютные RMS дБ по 8 полосам) проходят свой гейт
assert qg.judge([-26.3, -23.0, -29.6, -28.9, -33.2, -39.9, -40.2, -44.1], 10.9, "anime lofi") == []
assert qg.judge([-23.1, -22.3, -31.3, -28.3, -30.3, -33.2, -34.2, -38.2], 1.5, "phonk") == []
assert len(qg.BANDS) == 8 and qg.BAND_TOL == 2.0
print("test_quality_gate OK")
