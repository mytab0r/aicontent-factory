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
                              budget_sec=1500, min_sec=0, now=lambda: next(clock))
    assert paths == ["t0", "t1"]


def test_mix_max_tracks_cap():
    paths, _ = music.plan_mix(10**6, lambda i: i, lambda p: 1.0, max_tracks=3, min_sec=0)
    assert len(paths) == 3


def test_mix_gated_segment_regenerated_fail_not_in_mix(tmp=None):
    """t_187762da: best-of-K на сегмент: все K кандидатов, гейт, MAX CE среди прошедших;
    брак (в т.ч. с FAIL по objective) в микс не попадает и удаляется с диска."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    made = []
    def raw(i, k):
        p = d / f"s{i}_{k}.mp3"
        p.write_bytes(b"x")
        made.append(p.name)
        return str(p)
    bad = {"s1_0.mp3"}  # сегмент 1, кандидат 0 — брак (как 17.10: полоса 20-60 Гц -2.2 дБ)
    scores = lambda fs: [[3.0] * 3 if Path(f).name in bad else [7.5] * 3 for f in fs]
    gen = music.gated_gen(raw, scores, lambda p: [], attempts=3, log=lambda *a: None)
    paths, durs = music.plan_mix(1500, gen, lambda p: 500.0)
    names = [Path(x).name for x in paths]
    assert names == ["s0_0.mp3", "s1_1.mp3", "s2_0.mp3"], names
    assert "s1_0.mp3" not in names and not (d / "s1_0.mp3").exists()  # брак удалён с диска
    assert made == ["s0_0.mp3", "s0_1.mp3", "s0_2.mp3",
                    "s1_0.mp3", "s1_1.mp3", "s1_2.mp3",
                    "s2_0.mp3", "s2_1.mp3", "s2_2.mp3"]  # все K кандидатов на сегмент


def test_mix_gated_segment_picks_max_ce_among_passing():
    """Выбор MAX CE среди прошедших (7.6 > 7.0 > 7.2), а не первого/минимального."""
    ce = {"s0_0": 7.0, "s0_1": 7.6, "s0_2": 7.2}
    scores = lambda fs: [[ce[Path(f).name]] * 3 for f in fs]
    gen = music.gated_gen(lambda i, k: f"s0_{k}", scores, lambda p: [], attempts=3,
                          log=lambda *a: None)
    assert gen(0) == "s0_1"
    # прошедших по objective двое, но у s0_2 CE ниже порога -> победитель s0_0
    obj = lambda p: ["FAIL"] if p == "s0_1" else []
    ce2 = {"s0_0": 7.0, "s0_1": 9.9, "s0_2": 6.4}
    scores2 = lambda fs: [[ce2[Path(f).name]] * 3 for f in fs]
    gen = music.gated_gen(lambda i, k: f"s0_{k}", scores2, obj, attempts=3, log=lambda *a: None)
    assert gen(0) == "s0_0"


def test_mix_segment_dropped_after_k_fails_if_mix_long_enough():
    seen = []
    def raw(i, k):
        seen.append((i, k))
        return f"s{i}_{k}"
    scores = lambda fs: [[3.0] * 3 if f.startswith("s1_") else [7.5] * 3 for f in fs]
    gen = music.gated_gen(raw, scores, lambda p: [], attempts=2, log=lambda *a: None)
    paths, _ = music.plan_mix(1500, gen, lambda p: 500.0, min_sec=900)
    assert paths == ["s0_0", "s2_0", "s3_0"], paths
    assert seen.count((1, 0)) == 1 and seen.count((1, 1)) == 1 and (1, 2) not in seen  # ровно K попыток


def test_mix_fails_if_under_15_min_after_drops():
    gen = music.gated_gen(lambda i, k: f"s{i}_{k}", lambda fs: [[3.0] * 3] * len(fs), lambda p: [],
                          attempts=2, log=lambda *a: None)
    try:
        music.plan_mix(3600, gen, lambda p: 500.0, max_tracks=4, min_sec=900)
        raise SystemExit("должен был упасть: микс < 15 мин")
    except RuntimeError as e:
        assert "15" in str(e) or "900" in str(e), e


def test_mix_gate_objective_fail_regenerates_and_critic_error_propagates():
    obj = lambda p: ["полоса 20-60 Гц -2.2 дБ к эталону"] if p == "s0_0" else []
    gen = music.gated_gen(lambda i, k: f"s{i}_{k}", lambda fs: [[7.9] * 3] * len(fs), obj,
                          attempts=3, log=lambda *a: None)
    assert gen(0) == "s0_1"
    def broken(fs):
        raise RuntimeError("критик не отработал (0/3)")
    gen = music.gated_gen(lambda i, k: f"s{i}_{k}", broken, lambda p: [], attempts=3, log=lambda *a: None)
    try:
        gen(0)
        raise SystemExit("ошибка критика должна валить шаг, не выкидывать сегмент")
    except RuntimeError as e:
        assert "критик" in str(e)


def test_daily_video_sets_bestof():
    import re
    wf = (Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")
    m = re.search(r'ACE15_BESTOF:\s*"?(\d+)', wf)
    assert m and int(m.group(1)) >= 2, "ACE15_BESTOF не задан в daily-video: отбор в проде не работает"


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
    # M4 (аудит 17.10): «| 1 Hour» при 56:15 (p-kkEmLGviU, ieY0WGw41dk, b9DA_1-VmP4) = misleading metadata.
    assert "Hour" not in pub.title_with_length(t, 3375)
    # ложная длина от LLM в самом заголовке вырезается, верная остаётся
    assert "Hour" not in pub.title_with_length("Cafe Lofi | 1 Hour", 3375)
    assert pub.title_with_length("Cafe Lofi | 1 Hour", 3700) == "Cafe Lofi | 1 Hour"
    assert pub.title_with_length("Cafe Lofi | 2 Hours", 3700) == "Cafe Lofi | 1 Hour"
    long = "x" * 99
    assert len(pub.title_with_length(long, 3700)) <= 100


def test_mix_segment_mastered_before_gate():
    """Ревью t_187762da: кандидат сегмента мастерится как прод ДО критика/objective —
    гейт меряет то, что уйдёт на канал (LOFI_AF меняет 20-60 Гц и LRA = метрики провала 17.10)."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    calls = []
    orig = music.generate_track_v15, music.mastering.master
    music.generate_track_v15 = lambda prompt, sec, seed, out, ref_audio=None: (
        calls.append(("gen", Path(out).name)), Path(out).write_bytes(b"x"))
    music.mastering.master = lambda s, d_, genre="": calls.append(("master", Path(s).name, genre))
    try:
        raw = music.mix_raw(d, "p", 1000, None, "anime lofi")
        def scores(fs):
            calls.append(("scores", [Path(f).name for f in fs]))
            return [[7.5] * 3 for _ in fs]
        def obj(p):
            calls.append(("objective", Path(p).name))
            return []
        assert Path(music.gated_gen(raw, scores, obj, attempts=2, log=lambda *a: None)(0)).name == "mix_00_0.mp3"
    finally:
        music.generate_track_v15, music.mastering.master = orig
    assert calls == [("gen", "mix_00_0.mp3"), ("master", "mix_00_0.mp3", "anime lofi"),
                     ("gen", "mix_00_1.mp3"), ("master", "mix_00_1.mp3", "anime lofi"),
                     ("scores", ["mix_00_0.mp3", "mix_00_1.mp3"]),
                     ("objective", "mix_00_0.mp3"), ("objective", "mix_00_1.mp3")], calls


def test_mix_raw_restarts_ace_on_failed_task():
    """t_ffa7ff01: stage=failed (CUDA illegal memory access) -> restart ace-step + 1 повтор; иное — наверх."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    calls = []
    orig = music.generate_track_v15, music.mastering.master, music.ace_restart

    def gen(prompt, sec, seed, out, ref_audio=None):
        calls.append("gen")
        if calls.count("gen") == 1:
            raise RuntimeError("ACE-Step 1.5 task x failed: stage failed")
        Path(out).write_bytes(b"x")
    music.generate_track_v15, music.mastering.master = gen, lambda *a, **k: None
    music.ace_restart = lambda: calls.append("restart")
    try:
        assert Path(music.mix_raw(d, "p", 1, None, "anime lofi")(0, 0)).exists()
        assert calls == ["gen", "restart", "gen"], calls
        music.generate_track_v15 = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout"))
        try:
            music.mix_raw(d, "p", 1, None, "anime lofi")(1, 0)
            raise AssertionError("timeout должен уйти наверх")
        except RuntimeError as e:
            assert "timeout" in str(e)
    finally:
        music.generate_track_v15, music.mastering.master, music.ace_restart = orig


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
