#!/usr/bin/env python3
"""Микс ~1 ч из нескольких цельных треков ACE-Step 1.5 + главы-треклист в описании.

Ресёрч 13.10: инструментальные хиты ниши = 1-4 ч, у 2/3 треклист с 0:00; наш 8:03 ниже нормы.
Запуск: python3 pipeline/test_mix.py
"""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


music = _load("music_mix", "03_music.py")


def test_mix_fills_target_with_actual_durations():
    made = []
    def gen(i):
        made.append(i)
        return f"t{i}.mp3"
    # модель отдаёт меньше запрошенного (600 -> 482 с), считаем по факту
    paths, durs = music.plan_mix(3600, gen, lambda p: 482.0)
    assert len(paths) == 8 and sum(durs) >= 3600          # 8 x 482 = 3856
    assert made == list(range(8))


def test_mix_stops_on_time_budget_but_keeps_tracks():
    clock = iter([0, 600, 1300])  # старт; после t0 (600+600<=1500); после t1 1300+650>1500 -> стоп
    paths, _ = music.plan_mix(3600, lambda i: f"t{i}", lambda p: 400.0,
                              budget_sec=1500, now=lambda: next(clock))
    assert paths == ["t0", "t1"]


def test_mix_max_tracks_cap():
    paths, _ = music.plan_mix(10**6, lambda i: i, lambda p: 1.0, max_tracks=3)
    assert len(paths) == 3


def test_chapters_start_at_zero_and_format_hours():
    ch = music.chapters([482.0, 482.0, 3000.0], ["A", "B", "C"])
    assert ch == ["0:00 A", "8:02 B", "16:04 C"]
    assert music.chapters([3700, 10], ["x", "y"])[1] == "1:01:40 y"


def test_track_names_unique_and_deterministic():
    a = music.track_names(8, seed=5)
    assert len(set(a)) == 8 and a == music.track_names(8, seed=5)


def test_description_gets_tracklist():
    pub = _load("pub_mix", "05_publish.py")
    d = pub.full_description("Cozy rain.", ["0:00 A", "8:02 B", "16:04 C"])
    assert "Tracklist:\n0:00 A\n8:02 B\n16:04 C" in d
    assert d.index("Tracklist") < d.index("#lofi")
    assert "Tracklist" not in pub.full_description("x")  # без глав (1 трек) — как раньше


def test_title_gets_real_length_label():
    pub = _load("pub_len", "05_publish.py")
    t = "Rainy Tokyo Pumpkin Caf\u00e9 \U0001f383 Cozy Lofi Beats to Study & Relax"
    assert pub.title_with_length(t, 3856) == t + " | 1 Hour"
    assert pub.title_with_length(t, 7300) == t + " | 2 Hours"
    assert pub.title_with_length(t, 482) == t  # < ~55 мин: без метки (не врём о длине)
    assert pub.title_with_length("Cafe 1 Hour Lofi", 3700) == "Cafe 1 Hour Lofi"  # уже есть
    long = "x" * 99
    assert len(pub.title_with_length(long, 3700)) <= 100


def test_mix_one_key_for_all_tracks():
    """Аудит 4HB26c4yow0: разные тональности треков = фальшь на стыках."""
    class Api:
        def __init__(self): self.bodies = []
        def post(self, path, body):
            if path == "/release_task":
                self.bodies.append(body); return {"data": {"task_id": "t"}}
            return {"data": [{"status": 1, "result": '[{"file": "/f"}]'}]}
        def get(self, path): return b"x"
    import tempfile
    api = Api()
    for i in range(3):
        music.generate_track_v15("p", 600, 100 + i, tempfile.mktemp(), api=api, key_seed=100)
    assert len({(b["key_scale"], b["bpm"]) for b in api.bodies}) == 1
    assert len({b["seed"] for b in api.bodies}) == 3  # разные треки, одна тональность


def test_stitch_cmd_trims_crossfades_normalizes():
    cmd = " ".join(music.stitch_cmd(["a.mp3", "b.mp3", "c.mp3"], "out.mp3"))
    assert cmd.count("acrossfade=d=4.0") == 2
    assert cmd.count("areverse") == 6 and "-45dB" in cmd
    assert "loudnorm=I=-14:TP=-1.5" in cmd and "concat" not in cmd


def test_chapters_account_for_crossfade():
    assert music.mix_starts([480.0, 470.0, 460.0]) == [476.0, 466.0, 460.0]


def test_stitch_real_audio_no_gap():
    """ffmpeg по-настоящему: дыра в 3 с тишины в конце трека не попадает в микс."""
    import subprocess, tempfile
    d = Path(tempfile.mkdtemp())
    for n, extra in (("a", ",apad=pad_dur=3"), ("b", "")):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"sine=f=440:d=10{extra}", str(d / f"{n}.mp3")], check=True)
    subprocess.run(music.stitch_cmd([d / "a.mp3", d / "b.mp3"], d / "o.mp3"), check=True)
    total = music._probe_sec(d / "o.mp3")
    assert 15 < total < 17.5, total  # 10+10-4, без 3 с тишины
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(d / "o.mp3"), "-af",
                          "silencedetect=n=-45dB:d=0.5", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    assert "silence_start" not in err.split("Output")[-1].replace("silence_start: 0\n", ""), err[-500:]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
