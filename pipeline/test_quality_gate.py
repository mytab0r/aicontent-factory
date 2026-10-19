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
# V1: чёрные кадры >= 2 с в финальном mp4 = FAIL; тёмная ночная сцена (обложки канала YAVG 41-88) проходит.
with tempfile.TemporaryDirectory() as td:
    ok, dark, blk = f"{td}/ok.mp4", f"{td}/dark.mp4", f"{td}/blk.mp4"
    for out, vf in ((ok, "color=c=gray:s=64x64:r=5:d=10"), (dark, "color=c=0x282828:s=64x64:r=5:d=10"),
                    (blk, "color=c=gray:s=64x64:r=5:d=10,drawbox=c=black:t=fill:enable='between(t,4,7)'")):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", vf, "-c:v", "libx264", out], check=True)
    assert qg.black_why(ok) == [] and qg.black_why(dark) == [], (qg.black_why(ok), qg.black_why(dark))
    assert any("чёрн" in w for w in qg.black_why(blk)), qg.black_why(blk)
# t_3f0f7b91: гейт сегмента (gated_gen/best-of) берёт CE КАЖДОГО окна 30 с, а не 3 отрывка: 100 с = 4 окна
with tempfile.TemporaryDirectory() as td:
    a, b = f"{td}/a.wav", f"{td}/b.wav"
    for out, d in ((a, 100), (b, 45)):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=f=220:d={d}", "-ac", "2", out], check=True)
    seen = []
    res = qg.ce_windows_batch([a, b], critic=lambda ps: seen.extend(ps) or [7.0 + i / 100 for i in range(len(ps))])
    assert [len(x) for x in res] == [4, 2] and len(seen) == 6, (res, seen)
    assert res[1] == [7.04, 7.05], res
# t_3f0f7b91: реальные CE эталона ref1 (критик, run 39150963005): хвостовое окно 90.024 не удваивает вес хвоста в R2
ref1 = [(0.0, 7.548), (30.0, 7.296), (60.0, 7.191), (90.0, 6.789), (90.024, 6.767)]
assert qg.ce_why(ref1) == [], qg.ce_why(ref1)
assert qg.ce_why([(0, 7.5), (30, 7.5), (60, 6.9), (90, 6.9), (90.024, 6.9)])  # настоящий дрейф 0.6 ловится
# A16 (каталог): обрыв без затухания = FAIL; трек с затуханием 3 с (как у эталонов: хвост -45 дБ к треку) проходит
with tempfile.TemporaryDirectory() as td:
    cut_end, faded = f"{td}/cut.wav", f"{td}/fade.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=20", "-ac", "2", cut_end], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=20", "-af",
                    "afade=t=out:st=17:d=3", "-ac", "2", faded], check=True)
    assert any("резкий конец" in w for w in qg.end_why(cut_end)), qg.end_why(cut_end)
    assert qg.end_why(faded) == [], qg.end_why(faded)
print("test_quality_gate OK")

# V3 (каталог): шортс не 9:16 / длиннее 60 с / без звука = YouTube не покажет его в ленте Shorts (уйдёт обычным роликом)
with tempfile.TemporaryDirectory() as td:
    def mk(out, size, d, audio=True):
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s={size}:r=5:d={d}"]
        cmd += (["-f", "lavfi", "-i", f"sine=f=440:d={d}", "-c:a", "aac"] if audio else []) + ["-c:v", "libx264", "-pix_fmt", "yuv420p", out]
        subprocess.run(cmd, check=True)
    ok, wide, long_, mute = (f"{td}/{n}.mp4" for n in ("ok", "wide", "long", "mute"))
    mk(ok, "108x192", 40); mk(wide, "192x108", 40); mk(long_, "108x192", 61); mk(mute, "108x192", 40, audio=False)
    assert qg.short_why(ok) == [], qg.short_why(ok)
    assert any("9:16" in w for w in qg.short_why(wide)), qg.short_why(wide)
    assert any("60" in w for w in qg.short_why(long_)), qg.short_why(long_)
    assert any("поток" in w for w in qg.short_why(mute)), qg.short_why(mute)
print("test_quality_gate V3 short-format OK")

# A9 (каталог): каналы в противофазе = в моно трек пропадает; нормальное стерео и моно-файл проходят
with tempfile.TemporaryDirectory() as td:
    inv, ok, mono = f"{td}/inv.wav", f"{td}/ok.wav", f"{td}/mono.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=5", "-af",
                    "pan=stereo|c0=c0|c1=-1*c0", inv], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=5", "-ac", "2", ok], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=5", mono], check=True)
    assert any("моно" in w for w in qg.stereo_why(inv)), qg.stereo_why(inv)
    assert qg.stereo_why(ok) == [] and qg.stereo_why(mono) == [], (qg.stereo_why(ok), qg.stereo_why(mono))
    assert qg.MONO_LOSS == 3.0
print("test_quality_gate A9 stereo OK")
