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
# true peak (A5): клиппинг ловится, эталоны (ref1 TP -1.6, v2 -2.9) проходят
with tempfile.TemporaryDirectory() as td:
    hot = f"{td}/hot.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=3000:d=10", "-af", "volume=24dB",
                    "-ac", "2", "-c:a", "pcm_f32le", hot], check=True)
    w_hot, m_hot = qg.objective(hot, "phonk")
    assert any("true peak" in w for w in w_hot), (w_hot, m_hot)
# A13 (17.10): гейт мерил track.mp3, а на YouTube ушёл AAC в mp4 с TP +1.3..+1.9 dBTP (p-kkEmLGviU).
# --final обязан мерить video.mp4 и ловить пики в финальном файле; одобренные эталоны после AAC 192k проходят.
from pathlib import Path as _P
assert qg.target(_P("r"), True) == _P("r/video.mp4") and qg.target(_P("r"), False) == _P("r/track.mp3")
with tempfile.TemporaryDirectory() as td:
    v = f"{td}/video.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=5:d=10",
                    "-f", "lavfi", "-i", "sine=f=3000:d=10", "-af", "volume=24dB", "-ac", "2",
                    "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", "-shortest", v], check=True)
    w_v, m_v = qg.objective(v, "phonk")
    assert any("true peak" in w for w in w_v), (w_v, m_v)
    assert qg.main(["x", v, "phonk", "--final"]) == 1
# A6: обрыв 3 с посреди трека = FAIL; штатное затухание в хвосте (ref1: тишина 6.5 с в последние 10 с) проходит
with tempfile.TemporaryDirectory() as td:
    gap, tail = f"{td}/gap.wav", f"{td}/tail.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=60",
                    "-af", "volume='if(between(t,30,33),0,1)':eval=frame", "-ac", "2", gap], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=60",
                    "-af", "volume='if(gt(t,53.5),0,1)':eval=frame", "-ac", "2", tail], check=True)
    g = qg.gaps(gap)
    assert len(g) == 1 and 29.5 < g[0][0] < 30.5 and g[0][1] >= 2.5, g
    assert any("тишина" in w for w in qg.objective(gap, "anime lofi")[0])
    assert qg.gaps(tail) == [], qg.gaps(tail)
# A15: тихий финал (-30 LUFS) = FAIL; эталоны ref1 -15.1 и v2 -13.9 LUFS проходят; громче -13 = FAIL
assert qg.loud_why(-15.1) == [] and qg.loud_why(-13.9) == []
assert qg.loud_why(-12.0) and qg.loud_why(-17.0)
with tempfile.TemporaryDirectory() as td:
    q = f"{td}/quiet.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=20", "-af", "volume=-20dB",
                    "-ac", "2", q], check=True)
    w_q, m_q = qg.objective(q, "anime lofi")
    assert m_q["i"] < -16 and any("LUFS" in w for w in w_q), (w_q, m_q)
# V2/V3: 13-16.10 четыре ролика P0D. Целый mp4 проходит; без видео, рассинхрон, длина != треку = FAIL.
with tempfile.TemporaryDirectory() as td:
    def mk(out, vd, ad, vid=True):
        cmd = ["ffmpeg", "-loglevel", "error", "-y"] + (["-f", "lavfi", "-i", f"color=c=gray:s=64x64:r=5:d={vd}"] if vid else [])
        cmd += ["-f", "lavfi", "-i", f"sine=f=440:d={ad}", "-ac", "2"] + (["-c:v", "libx264"] if vid else []) + ["-c:a", "aac", out]
        subprocess.run(cmd, check=True)
    ok, nov, desync = f"{td}/ok.mp4", f"{td}/nov.mp4", f"{td}/ds.mp4"
    mk(ok, 10, 10); mk(nov, 0, 10, vid=False); mk(desync, 3, 10)
    assert qg.integrity_why(ok, 10.0) == [], qg.integrity_why(ok, 10.0)
    assert any("нет потока" in w for w in qg.integrity_why(nov)), qg.integrity_why(nov)
    assert any("рассинхрон" in w for w in qg.integrity_why(desync)), qg.integrity_why(desync)
    assert any("!= трек" in w for w in qg.integrity_why(ok, 900.0)), qg.integrity_why(ok, 900.0)
print("test_quality_gate OK")
