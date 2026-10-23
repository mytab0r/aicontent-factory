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


def _mk(path, w, h, d, color="0x3a6ea5"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:d={d}:r=10",
                    "-f", "lavfi", "-i", f"sine=f=220:d={d}", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)
    return str(path)


def test_video_gate_on_render_json():
    if not shutil.which("ffmpeg"):
        print("skip: нет ffmpeg")
        return
    import quality_gate as qg
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        good = {"long": _mk(d / "long.mp4", 320, 180, 4), "shorts": [_mk(d / "s1.mp4", 180, 320, 3)]}
        (d / "render.json").write_text(json.dumps(good))
        assert qg.video_why(d) == [], qg.video_why(d)
        # брак: шортс горизонтальный, long чёрный 4 с
        bad = {"long": _mk(d / "blk.mp4", 320, 180, 4, "black"), "shorts": [_mk(d / "s2.mp4", 320, 180, 3)]}
        (d / "render.json").write_text(json.dumps(bad))
        why = " | ".join(qg.video_why(d))
        assert "чёрный кадр" in why and "не 9:16" in why, why
        # owning: нет render.json, video.mp4 = Short
        (d / "render.json").unlink()
        _mk(d / "video.mp4", 180, 320, 3)
        assert qg.video_why(d) == [], qg.video_why(d)


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
