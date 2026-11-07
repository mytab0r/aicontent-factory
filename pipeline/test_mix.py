#!/usr/bin/env python3
"""Микс ~1 ч из нескольких цельных треков ACE-Step 1.5 + главы-треклист в описании.

Ресёрч 13.10: инструментальные хиты ниши = 1-4 ч, у 2/3 треклист с 0:00; наш 8:03 ниже нормы.
Запуск: python3 pipeline/test_mix.py
"""
import importlib.util
import re
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


def test_mix_survives_streak_of_drops_within_budget():
    """20.10 run 39353766781: сегмент 0 OK, 1-3 выбракованы гейтом -> plan_mix встал после
    3 провалов подряд на 55-й минуте из 120 бюджета, выпуск lofi сорван (180 с < 900 с).
    Серия провалов внутри бюджета не повод сдаваться: нужен потолок 5 подряд + бюджет."""
    ok = {0, 4, 5, 6, 7}
    gen = lambda i: f"t{i}" if i in ok else None
    paths, durs = music.plan_mix(3600, gen, lambda p: 180.0, max_tracks=22, min_sec=900)
    assert paths == ["t0", "t4", "t5", "t6", "t7"], paths


def test_mix_drops_bounded_by_time_budget():
    """Провалы тоже тратят бюджет: сплошной брак останавливается по времени, а не крутится."""
    t = iter(range(0, 10**6, 1000))
    calls = []
    def gen(i):
        calls.append(i)
        return None
    try:
        music.plan_mix(3600, gen, lambda p: 180.0, budget_sec=2500, max_drops=99,
                       max_tracks=99, min_sec=900, now=lambda: next(t))
        raise SystemExit("должен был упасть: микс пуст")
    except RuntimeError:
        pass
    assert len(calls) <= 4, calls


def test_bank_fill_sets_bestof():
    """t_ba72c7aa R5: отбор best-of остался в ГЕНЕРАТОРЕ (bank-fill), из daily-video удалён."""
    import re
    bf = (Path(__file__).resolve().parent.parent / ".github/workflows/bank-fill.yml").read_text(encoding="utf-8")
    m = re.search(r'ACE15_BESTOF:\s*"?(\d+)', bf)
    assert m and int(m.group(1)) >= 2, "ACE15_BESTOF не задан в bank-fill: отбор в генераторе банка не работает"


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
    assert len(pub.title_with_length(long, 3700)) <= 70


def test_title_fits_feed_70():
    """V12: заголовок <= 70 символов вместе с «| 1 Hour», обрез по слову, начало (сцена+жанр) цело."""
    pub = _load("pub_v12", "05_publish.py")
    t = "Rainy Tokyo Pumpkin Caf\u00e9 \U0001f383 Cozy Lofi Beats to Study and Relax to Tonight"
    for d in (3856, 7300, 482, 3375):
        r = pub.title_with_length(t, d)
        assert len(r) <= 70, (len(r), r)
        assert r.startswith("Rainy Tokyo Pumpkin Caf\u00e9 \U0001f383 Cozy Lofi"), r
        assert not re.search(r"\b(to|and|&)$", r.split(" | ")[0]), r
    assert pub.title_with_length(t, 3856).endswith(" | 1 Hour")
    short = "Cafe Lofi Beats"
    assert pub.title_with_length(short, 3700) == short + " | 1 Hour"


def test_mix_segment_mastered_before_gate():
    """Ревью t_187762da: кандидат сегмента мастерится как прод ДО критика/objective —
    гейт меряет то, что уйдёт на канал (мастер меняет 20-60 Гц и LRA = метрики провала 17.10)."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    calls = []
    orig = music.generate_track_v15, music.mastering.master
    music.generate_track_v15 = lambda prompt, sec, seed, out, ref_audio=None, **k: (
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

    def gen(prompt, sec, seed, out, ref_audio=None, **k):
        calls.append("gen")
        if calls.count("gen") == 1:
            raise RuntimeError("ACE-Step 1.5 task x failed: stage failed")
        Path(out).write_bytes(b"x")
    music.generate_track_v15, music.mastering.master = gen, lambda *a, **k: None
    music.ace_restart = lambda: calls.append("restart")
    try:
        assert Path(music.mix_raw(d, "p", 1, None, "anime lofi")(0, 0)).exists()
        assert calls == ["gen", "restart", "gen"], calls
        music.generate_track_v15 = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            music.mix_raw(d, "p", 1, None, "anime lofi")(1, 0)
            raise AssertionError("прочая ошибка должна уйти наверх")
        except RuntimeError as e:
            assert "boom" in str(e)
    finally:
        music.generate_track_v15, music.mastering.master, music.ace_restart = orig


def test_edge_match_levels_seam_rms():
    """t_ffa7ff01: gain-райд выравнивает края сегментов под порог R3 (3 дБ); клэмп ±6 дБ/проход."""
    import subprocess as sp
    import tempfile
    d = Path(tempfile.mkdtemp())
    fs = []
    for k, v in enumerate((0.56, 0.28, 0.28)):  # A правый край на ~6 дБ громче B левого, C уже выровнен
        f = d / f"{k}.mp3"
        sp.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=30",
                "-af", f"volume={v}", "-c:a", "libmp3lame", "-b:a", "192k", str(f)], check=True)
        fs.append(str(f))
    gains = music.edge_match(fs, log=lambda *x: None)
    assert len(gains) == 3 and gains[0] == 0.0, gains
    dl = [abs(music.edge_rms(fs[i], "l") - music.edge_rms(fs[i - 1], "r")) for i in (1, 2)]
    assert dl[0] <= 3.0 and dl[1] <= 3.0, dl
    # клэмп: сегмент тише края на 40 дБ -> максимум 3 прохода по 6 дБ, без бесконечного цикла
    f = d / "deep.mp3"
    sp.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=30",
            "-af", "volume=0.0056", "-c:a", "libmp3lame", "-b:a", "192k", str(f)], check=True)
    g2 = music.edge_match([fs[0], str(f)], log=lambda *x: None)
    # клэмп: <= 3 x 6 дБ, без бесконечного цикла. Не ровно 18: стык мерится по склейке (t_e0c297c7),
    # в окне справа от центра кроссфейда ещё звучит prev, поэтому разница < 40 дБ и последний проход < 6.
    assert 12.0 < g2[1] <= music.EDGE_MAX_GAIN, g2


def test_edge_match_no_chain_drift():
    """run 39670128584: каждый сегмент ACE-Step громче в начале, чем в конце (~6 дБ). Старый edge_match
    тянул ВЕСЬ сегмент к краю предыдущего -> gain копился по цепочке -3.8..-18 дБ, упирался в клэмп,
    стык 1445 с -14.5 -> -18.1 дБ = R3 FAIL. Нужно: каждый стык <= 3 дБ при любой длине цепочки,
    тело сегментов не уезжает (середина каждого сегмента в пределах 1 дБ от исходной)."""
    import subprocess as sp
    import tempfile
    d = Path(tempfile.mkdtemp())
    fs = []
    for k in range(7):
        f = d / f"ch{k}.mp3"
        sp.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=90",
                "-af", "volume='0.5*pow(10,-6*t/90/20)':eval=frame", "-c:a", "libmp3lame", "-b:a", "192k", str(f)],
               check=True)
        fs.append(str(f))
    mid0 = music.edge_rms(fs[3], "r", sec=50.0)
    music.edge_match(fs, log=lambda *x: None)
    jumps = [abs(music.edge_rms(fs[i], "l") - music.edge_rms(fs[i - 1], "r")) for i in range(1, len(fs))]
    assert max(jumps) <= 3.0, jumps
    assert abs(music.edge_rms(fs[3], "r", sec=50.0) - mid0) <= 1.0


def test_prep_segments_trims_fade_before_edge_match():
    """run 39326466292: edge_match до trim_fade_tails мерил тихий хвост-затухание -> сегменты 2-5
    задавлены на -18 дБ, R3 стык 336 с -16.2 -> -19.6 дБ. Одинаковые по телу сегменты с фейдом
    в конце после prep_segments почти не получают gain и стыки <= 3 дБ."""
    import subprocess as sp
    import tempfile
    d = Path(tempfile.mkdtemp())
    fs = []
    for k in range(4):
        f = d / f"pf{k}.mp3"
        sp.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=40",
                "-af", "volume=0.5,afade=t=out:st=28:d=12:curve=exp", "-c:a", "libmp3lame", "-b:a", "192k", str(f)],
               check=True)
        fs.append(str(f))
    gains = music.prep_segments(fs, log=lambda *x: None)
    assert all(abs(g) <= 1.5 for g in gains), gains
    for i in range(1, len(fs)):
        assert abs(music.edge_rms(fs[i], "l") - music.edge_rms(fs[i - 1], "r")) <= 3.0

def test_trim_fade_tails_cuts_quiet_end_and_respects_last():
    "trim_fade_tails: срезает хвост-затухание (RMS ниже медианы на 6 дБ), последний сегмент не трогаем; после среза края сегментов на уровне тела (R3)."
    import subprocess
    import tempfile
    _m = music
    tdir = tempfile.mkdtemp()
    fs = []
    for k in range(3):
        f = f"{tdir}/tf{k}.mp3"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=30",
                        "-af", "volume=0.5,afade=t=out:st=22:d=8:curve=exp",
                        "-c:a", "libmp3lame", "-b:a", "192k", f], check=True)
        fs.append(f)
    cuts = _m.trim_fade_tails(fs[:-1])
    assert cuts[0] >= 5, cuts  # хвост 8 с затухания срезан
    d30 = _m._probe_sec(fs[0])
    assert d30 < 28, d30       # файл реально короче
    assert _m._probe_sec(fs[-1]) >= 29, "последний сегмент не режется"
    # после среза правый край сегмента 0 на уровне тела (отклонение < 6 дБ)
    body = _m.edge_rms(fs[0], "l", sec=10)
    tail = _m.edge_rms(fs[0], "r", sec=5)
    assert abs(tail - body) < 6, (body, tail)

def test_fade_end_passes_a16_after_loudnorm():
    """run 39395729278 (20.10): 03c FAIL «резкий конец: последние 0.5 с -25.6 дБ при треке -15.8 (затухание -9.7 < 12)».
    Хвост последнего сегмента ACE-Step обрывается, loudnorm его подтягивает. fade_end после мастеринга -> A16 проходит."""
    import subprocess as sp
    import tempfile
    import quality_gate as qg
    d = Path(tempfile.mkdtemp())
    f = d / "end.mp3"
    sp.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=30", "-ac", "2",
            "-af", "loudnorm=I=-14:TP=-2:LRA=11", "-c:a", "libmp3lame", "-b:a", "192k", str(f)], check=True)
    assert qg.end_why(str(f)), "фикстура должна обрываться (RED-условие)"
    dur = music._probe_sec(f)
    music.fade_end(f)
    assert qg.end_why(str(f)) == [], qg.end_why(str(f))
    assert abs(music._probe_sec(f) - dur) < 0.1, "длительность не меняется (главы/стыки)"


def test_mix_segment_extra_candidates_only_when_all_fail():
    """t_f0794976, run 39450050733: 3 сегмента из 9 дали 0/3 (max CE 6.49/6.13/6.43 < 6.5).
    Порог не трогаем: сегменту с 0 прошедших дозаказываем extra кандидатов (3 -> 5),
    сегменты с OK из первых 3 лишнего GPU не тратят."""
    made = []
    def raw(i, k):
        made.append((i, k))
        return f"s{i}_{k}"
    ce = {"s0_0": 7.0, "s0_1": 6.4, "s0_2": 6.4, "s1_0": 6.49, "s1_1": 6.13, "s1_2": 6.43, "s1_3": 6.2, "s1_4": 6.8}
    scores = lambda fs: [[ce.get(f, 6.0)] * 3 for f in fs]
    gen = music.gated_gen(raw, scores, lambda p: [], attempts=3, extra=2, log=lambda *a: None)
    assert gen(0) == "s0_0" and (0, 3) not in made
    assert gen(1) == "s1_4", made
    assert made.count((1, 3)) == 1 and made.count((1, 4)) == 1 and (1, 5) not in made
    gen0 = music.gated_gen(raw, scores, lambda p: [], attempts=3, extra=0, log=lambda *a: None)
    assert gen0(1) is None


def test_mix_raw_hung_task_restarts_with_short_timeout():
    """21.10 run 39536019351: задача сегмента висела status=0 40 мин (норма ~2 мин) при
    timeout 2400 с -> весь выпуск упал, 2 готовых сегмента потеряны. Сегмент ждёт
    MIX_TASK_TIMEOUT (<=900 с), зависание = restart ace-step + 1 повтор."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    calls, tmo = [], []
    orig = music.generate_track_v15, music.mastering.master, music.ace_restart

    def gen(prompt, sec, seed, out, ref_audio=None, timeout_sec=2400, **k):
        calls.append("gen"); tmo.append(timeout_sec)
        if calls.count("gen") == 1:
            raise RuntimeError("ACE-Step 1.5 task abc timeout")
        Path(out).write_bytes(b"x")
    music.generate_track_v15, music.mastering.master = gen, lambda *a, **k: None
    music.ace_restart = lambda: calls.append("restart")
    try:
        assert Path(music.mix_raw(d, "p", 1, None, "anime lofi")(0, 0)).exists()
    finally:
        music.generate_track_v15, music.mastering.master, music.ace_restart = orig
    assert calls == ["gen", "restart", "gen"], calls
    assert all(x <= 900 for x in tmo), tmo


def test_edge_match_measures_crossfaded_seam_like_gate():
    """t_e0c297c7 (runs 40070541695 R3 641 с -20.3 -> -25.1, 40075415222 R3 961 с -23.7 -> -19.6): edge_match мерил
    последние 5 с prev и первые 5 с nxt в сырых файлах, гейт R3 меряет склейку ±5 с от центра 16-с кроссфейда
    (prev -13..-3 с, nxt 3..13 с). Удар в первые 5 с nxt (gain -8.6 дБ не туда) и брейкдаун перед последними 5 с
    prev давали R3 FAIL после prep_segments. Проверка тем же кодом, что гейт: rms_db + seam_why."""
    import subprocess as sp
    import tempfile
    import quality_gate as qg
    d = Path(tempfile.mkdtemp())

    def seg(name, expr, seed):
        f = d / name
        sp.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"anoisesrc=d=60:c=pink:a=0.25:seed={seed}",
                "-af", f"volume='{expr}':eval=frame", "-c:a", "libmp3lame", "-b:a", "192k", str(f)], check=True)
        return str(f)
    fs = [seg("a.mp3", "1", 1), seg("b.mp3", "if(lt(t,5),2.5,if(between(t,47,54),0.4,1))", 2), seg("c.mp3", "1", 3)]
    music.prep_segments(fs, log=lambda *x: None)
    out = str(d / "mix.mp3")
    _, ts = music.concat_tracks(fs, out)
    seams = [{"t": t, "ce": 9.0, "rms_l": qg.rms_db(out, t - qg.SEAM_HALF, qg.SEAM_HALF),
              "rms_r": qg.rms_db(out, t, qg.SEAM_HALF)} for t in ts]
    assert qg.seam_why(seams) == [], seams
    # t_2be41a12: запас 1 дБ до порога R3 — остаток ~3 дБ (xfade-fallback 3.12) проходил/падал от окружения
    assert all(abs(x["rms_l"] - x["rms_r"]) <= qg.SEAM_RMS_MAX - 1 for x in seams), seams


def test_edge_match_quiet_intro_full_gain_in_gate_window():
    """t_44f5c3b3 (runs 40477529845 R3 595 с -17.0 -> -21.0, 40508302240 R3 1312 с -16.3 -> -20.2): у сегмента банка
    тихое вступление (~-14 дБ к телу) длиннее DJ-перехода. edge_match давал gain +16/+15 дБ, но рампа спадала с t=0,
    в окно гейта (центр стыка ± SEAM_HALF) доходила лишь часть -> стык 4 дБ после всех проходов. Синтетика с
    бит-сеткой 72 BPM (dj_plan = DJ-стык как в банке), проверка тем же кодом, что гейт R3 (rms_db + seam_why)."""
    import subprocess as sp
    import tempfile
    import quality_gate as qg
    d = Path(tempfile.mkdtemp())

    def seg(name, vol, seed, dur=150):
        f = d / name
        sp.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"anoisesrc=d={dur}:c=pink:a=0.08:seed={seed}",
                "-f", "lavfi", "-i", f"sine=f=55:d={dur}", "-filter_complex",
                "[1:a]volume='0.9*exp(-12*mod(t,0.8333))':eval=frame[k];"
                f"[0:a][k]amix=inputs=2:normalize=0,volume='{vol}':eval=frame",
                "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", str(f)], check=True)
        return str(f)
    fs = [seg("a.mp3", "1", 1), seg("q.mp3", "if(lt(t,60),0.15,1)", 2), seg("c.mp3", "1", 3)]
    music.prep_segments(fs, log=lambda *x: None)
    out = str(d / "mix.mp3")
    _, ts = music.concat_tracks(fs, out)
    seams = [{"t": t, "ce": 9.0, "rms_l": qg.rms_db(out, t - qg.SEAM_HALF, qg.SEAM_HALF),
              "rms_r": qg.rms_db(out, t, qg.SEAM_HALF)} for t in ts]
    assert len(ts) == 2 and qg.seam_why(seams) == [], seams


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
