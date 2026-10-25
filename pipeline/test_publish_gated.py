#!/usr/bin/env python3
"""P19: каждый workflow с публикацией обязан прогнать quality_gate ДО первого шага заливки;
гейт видео-форматов (listshow/whatif/owning) ловит битый/чёрный/не-9:16 файл. Запуск: python3 pipeline/test_publish_gated.py"""
import json, pathlib, re, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
PUB = re.compile(r"python3?\s+(05_publish\.py|07_shorts\.py|\w+_channel\.py\s+publish)")


def ungated(text):
    """Номер строки первой заливки, если до неё нет вызова quality_gate.py; иначе None."""
    gate = False
    for n, line in enumerate(text.splitlines(), 1):
        s = line.split("#")[0]
        if "quality_gate.py" in s:
            gate = True
        if PUB.search(s):
            return None if gate else n
    return None


def test_every_publishing_workflow_is_gated():
    bad = {p.name: ungated(p.read_text(encoding="utf-8")) for p in (ROOT / ".github/workflows").glob("*.yml")}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, f"заливка без quality_gate до неё: {bad}"


def test_ungated_detects_listshow_shape():
    assert ungated("run: python render\nrun: ../.venv/bin/python listshow_channel.py publish") == 2
    assert ungated("run: ../.venv/bin/python quality_gate.py --video\nrun: ../.venv/bin/python listshow_channel.py publish") is None


def _mk(path, w, h, d, color="0x3a6ea5", audio=None):
    # A25: звук фикстуры в окне речи (-15 LUFS, TP -11); брак задаётся audio=
    audio = audio or f"sine=f=220:d={d},volume=7dB"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:d={d}:r=10",
                    "-f", "lavfi", "-i", audio, "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)
    return str(path)


def test_video_gate_on_render_json():
    if not shutil.which("ffmpeg"):
        print("skip: нет ffmpeg")
        return
    import quality_gate as qg
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        good = {"long": _mk(d / "long.mp4", 1920, 1080, 4), "shorts": [_mk(d / "s1.mp4", 1080, 1920, 3)]}
        (d / "render.json").write_text(json.dumps(good))
        assert qg.video_why(d) == [], qg.video_why(d)
        # брак: шортс горизонтальный, long чёрный 4 с
        bad = {"long": _mk(d / "blk.mp4", 1920, 1080, 4, "black"), "shorts": [_mk(d / "s2.mp4", 320, 180, 3)]}
        (d / "render.json").write_text(json.dumps(bad))
        why = " | ".join(qg.video_why(d))
        assert "чёрный кадр" in why and "не 9:16" in why, why
        # owning: нет render.json, video.mp4 = Short
        (d / "render.json").unlink()
        _mk(d / "video.mp4", 1080, 1920, 3)
        assert qg.video_why(d) == [], qg.video_why(d)


def test_video_gate_speech_audio():
    """A25: речевые форматы (edge-tts) — громкость вне -16..-13 LUFS, TP > -1, тишина >= 2 с (сбой TTS пункта) = стоп.
    Замер 23.10 канала 2 (7 роликов с YouTube): I -14.5..-13.9, TP -1.5..-1.0, макс. пауза 1.52 с — проходят."""
    if not shutil.which("ffmpeg"):
        print("skip: нет ffmpeg")
        return
    import quality_gate as qg
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        quiet = _mk(d / "q.mp4", 1080, 1920, 4, audio="sine=f=220:d=4,volume=-6dB")  # -28 LUFS
        hot = _mk(d / "h.mp4", 180, 320, 4, audio="sine=f=220:d=4,volume=17.5dB")  # TP ~ -0.6
        hole = _mk(d / "g.mp4", 1080, 1920, 20, audio="aevalsrc='0.9*sin(2*PI*220*t)*not(between(t,3,7))':d=20")  # 4 с тишины
        assert any("громкость" in w for w in qg.speech_why(quiet)), qg.speech_why(quiet)
        assert any("true peak" in w for w in qg.speech_why(hot)), qg.speech_why(hot)
        assert any("тишина" in w for w in qg.speech_why(hole)), qg.speech_why(hole)
        (d / "render.json").write_text(json.dumps({"long": _mk(d / "l.mp4", 1920, 1080, 4), "shorts": [quiet]}))
        assert any("громкость" in w for w in qg.video_why(d)), qg.video_why(d)


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
