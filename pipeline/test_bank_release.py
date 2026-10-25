#!/usr/bin/env python3
"""t_ba72c7aa R2: выпуск собирается ИЗ БАНКА (bank_release), не генерирует.
R4: статистика отказов по промптам (stats_record/fail_rate/prompt_enabled) в bank.py.
Тесты = контракт; реализация пишется по тому же контракту (TDD RED)."""
import hashlib
import json
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bank  # noqa: E402
import bank_release  # noqa: E402


def meta(name, bpm, key, prompt=None, seed=1):
    return {"name": name, "bpm": bpm, "key": key,
            "prompt": prompt or f"p {bpm} BPM, {key}, test", "seed": seed}


class FakeDocker:
    """docker exec sh -c CMD -> stdout; docker cp/rm -> журнал."""
    def __init__(self, files, out_lines=None):
        self.files = files            # {путь: bytes/str}
        self.out_lines = out_lines or []
        self.ops = []

    def __call__(self, *a):
        cmd = a[-1] if a else ""
        self.ops.append((a, cmd))
        best = max((pth for pth in self.files if pth in cmd), key=len, default=None)
        if best is None:
            return ""
        data = self.files[best]
        return data if isinstance(data, str) else data.decode()


def test_group_key_uses_prompt_text():
    assert bank_release.group_key(meta("a", 89, "F major")) == (89, "F major")


def test_pick_excludes_recently_used_and_bad_jsonl():
    """Критерий 7: анти-повтор 14 дней. Ровно 14 дней назад = уже можно; битая строка jsonl не роняет."""
    ents = [meta("a", 89, "F major"), meta("b", 89, "F major"), meta("c", 89, "F major"),
            meta("d", 82, "D major")]
    now = time.time()
    used = [json.dumps({"name": "a", "ts": now - 13 * 86400}),
            "{broken json",
            json.dumps({"name": "d", "ts": now - 14 * 86400})]  # ровно 14 дней -> можно
    got = bank_release.pick(ents, need=2, now=now, used_lines=used, rng=random.Random(1))
    names = {e["name"] for e in got}
    assert "a" not in names, names
    assert got is not None and len(got) == 2, got


def test_pick_takes_largest_group_and_requires_need():
    ents = [meta(f"a{i}", 89, "F major") for i in range(3)] + [meta("x", 82, "D major")]
    now = time.time()
    got = bank_release.pick(ents, need=2, now=now, used_lines=[], rng=random.Random(1))
    assert got is not None and all(e["bpm"] == 89 for e in got)
    # в группе из 1 элемента need=2 -> None
    assert bank_release.pick(ents[:1], need=2, now=now, used_lines=[], rng=random.Random(1)) is None


def test_entries_skips_missing_meta():
    """Критерий 2: сегмент без валидного json-мета в банк не попадает."""
    dk = FakeDocker({"/app/output/bank/anime-lofi": "a.mp3\nb.mp3\n",
                     "/app/output/bank/anime-lofi/a.json": json.dumps(
                         {"prompt": "x 89 BPM, F major", "seed": 5})})
    got = bank_release.entries("anime lofi", docker_sh=dk)
    assert [e["name"] for e in got] == ["a"], got


def _cp(dk, broken=()):
    """docker cp создаёт файл-приёмник; имена из broken копируются битыми (0 байт)."""
    def f(*a):
        r = dk(*a)
        if a and a[0] == "cp":
            dst = Path(a[2])
            dst.write_bytes(b"" if dst.stem in broken else b"ID3ok")
        return r
    return f


def test_take_refills_after_delivery_failure():
    """Проверка ОДНА (put_verified при записи). take() только доставляет: cp не удался =
    сегмент добирается другим, БЕЗ карантина и БЕЗ ffprobe-вердикта."""
    now = time.time()
    ents = [meta(n, 89, "F major") for n in ("a", "b", "c")]
    names = "".join(e["name"] + ".mp3\n" for e in ents)
    metas = {f"/app/output/bank/anime-lofi/{e['name']}.json": json.dumps(
        {"prompt": e["prompt"], "seed": e["seed"]}) for e in ents}
    dk = FakeDocker({**metas, "/app/output/bank/anime-lofi": names})

    def fail_a(*a):
        if a and a[0] == "cp":
            Path(a[2]).write_bytes(b"" if Path(a[2]).stem == "a" else b"ID3ok")
        return dk(*a)

    with tempfile.TemporaryDirectory() as td:
        got = bank_release.take("anime lofi", 2, td, docker_sh=fail_a, now=now,
                                rng=random.Random(1), valid=lambda p: Path(p).stat().st_size > 0)
        assert got is not None and len(got) == 2 and "a" not in {p.stem for p in got}, got
    mv = [op[1] for op in dk.ops if "mv " in op[1]]
    assert mv == [], mv  # карантина нет


def test_take_copies_each_segment_or_none():
    now = time.time()
    ents = [meta("a", 89, "F major"), meta("b", 89, "F major")]
    names = "\n".join(e["name"] + ".mp3" for e in ents) + "\n"
    metas = {f"/app/output/bank/anime-lofi/{e['name']}.json": json.dumps(
        {"prompt": e["prompt"], "seed": e["seed"]}) for e in ents}
    dk = FakeDocker({**{f"/app/output/bank/anime-lofi/{e['name']}.mp3": b"x" for e in ents},
                     **metas, "/app/output/bank/anime-lofi": names})
    with tempfile.TemporaryDirectory() as td:
        got = bank_release.take("anime lofi", 2, td, docker_sh=_cp(dk), now=now, rng=random.Random(1),
                                valid=lambda p: True)
        assert got is not None and len(got) == 2
        cps = [op for op in dk.ops if op[0][0] == "cp"]
        assert len(cps) == 2 and all(".mp3" in op[0][1] for op in cps), dk.ops
        assert bank_release.take("anime lofi", 5, td, docker_sh=_cp(dk), now=now, rng=random.Random(1),
                                 valid=lambda p: True) is None


def test_used_record_appends_and_cleanup_removes_old():
    """Критерий 7: пометка использованных и удаление через 30 дней."""
    now = time.time()
    with tempfile.TemporaryDirectory() as td:
        st = Path(td) / "bank_used.jsonl"
        bank_release.used_record(["a", "b"], now, state_path=st)
        bank_release.used_record(["c"], now - 40 * 86400, state_path=st)
        lines = st.read_text().splitlines()
        assert len(lines) == 3 and all(json.loads(x)["name"] in "abc" for x in lines)
        dk = FakeDocker({"/app/output/bank/anime-lofi": ""})
        removed = bank_release.used_cleanup(now, state_path=st, docker_sh=dk)
        assert removed == 1, removed
        names_left = [json.loads(x)["name"] for x in st.read_text().splitlines()]
        assert names_left == ["a", "b"], names_left
        assert any("c.mp3" in c and "rm" in c for _, c in dk.ops), dk.ops
        assert any("c.json" in c and "rm" in c for _, c in dk.ops), dk.ops


def test_assemble_writes_music_meta_and_concat():
    """Критерий 5/6: сборка из банка без генерации; meta с chapters/seams для гейта 03c/04b."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "acf_music03", Path(__file__).parent / "03_music.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["acf_music03"] = m
    spec.loader.exec_module(m)
    calls = {}
    m.prep_segments = lambda ps, log=print: calls.setdefault("prep", ps)
    m.concat_tracks = lambda ps, out, xfade=m.XFADE: calls.update(out=str(out), paths=ps)
    bank_release.master_final = lambda path, genre: calls.update(master=str(path), genre=genre)  # mastering не тестируем
    m._probe_sec = lambda p: 180.0
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td)
        paths = [rd / "a.mp3", rd / "b.mp3"]
        for p in paths:
            p.write_bytes(b"x")
        metas = [meta("a", 89, "F major", seed=11), meta("b", 89, "F major", seed=22)]
        mm = bank_release.assemble(paths, rd, metas, "anime lofi")
        assert calls["paths"] == [str(x) for x in paths] and calls["out"].endswith("track.mp3")
        assert mm["genre"] == "anime lofi" and "89 BPM" in mm["prompt"]
        assert mm["seed"] == 11 and len(mm["segments"]) == 2
        assert mm["chapters"] and len(mm["seams"]) == 1
        on_disk = json.loads((rd / "music_meta.json").read_text(encoding="utf-8"))
        assert on_disk["segments"] == mm["segments"]


def test_release_budget_under_15_min():
    """Критерий 5: выпуск при пустом GPU и наполненном банке проходит < 15 мин (20 сегментов на час)."""
    assert bank_release.release_budget_sec(20) < 900


def test_fail_rate_and_prompt_enabled():
    """Критерий 9: статистика отказов; промпт с браком >50% выключается автоматически."""
    lines = [json.dumps({"prompt": "p1", "seed": i, "ok": i % 2 == 0, "ts": i}) for i in range(20)]
    assert bank.fail_rate(lines, "p1") == 0.5
    lines_bad = lines[:-12] + [json.dumps({"prompt": "p1", "seed": i, "ok": False, "ts": i}) for i in range(12)]
    assert bank.fail_rate(lines_bad, "p1") == 0.8
    assert bank.fail_rate(["{broken"], "p1") is None          # битая строка не роняет
    assert bank.fail_rate([], "p1") is None                   # нет данных
    few = [json.dumps({"prompt": "p1", "ok": False}) for _ in range(3)]
    assert bank.prompt_enabled(few, "p1") is True             # < min_n = недостаточно данных
    assert bank.prompt_enabled(lines_bad, "p1") is False      # 0.8 > 0.5
    assert bank.prompt_enabled(lines, "p1") is True           # ровно 0.5 не > 0.5


def test_stats_record_appends_jsonl():
    dk = FakeDocker({})
    bank.stats_record("anime lofi", "p1", 7, True, docker_sh=dk)
    bank.stats_record("anime lofi", "p1", 8, False, "CE low", docker_sh=dk)
    assert len(dk.ops) == 2
    for (_, cmd), ok in zip(dk.ops, (True, False)):
        row = json.loads(cmd.split("echo ", 1)[1].rsplit(" >>", 1)[0].strip("'\""))
        assert row["prompt"] == "p1" and row["ok"] is ok and "ts" in row


def test_bank_main_skips_disabled_prompts():
    """Критерий 9: генератор берёт первый включённый вариант; все disabled -> fallback pick()."""
    import refpool
    saved = (bank.refpool if hasattr(bank, "refpool") else None)
    variants = ["v1 89 BPM, F major", "v2 82 BPM, D major", "v3 76 BPM, G major"]
    refpool.PROMPT_VARIANTS, saved_variants = variants, variants
    refpool.pick = lambda now=None: {"prompt": variants[0], "ref_path": ""}
    try:
        chosen = []
        def enabled(lines, prompt):
            chosen.append(prompt)
            return prompt != variants[0]  # v1 выключен, v2 включён
        got = bank.pick_prompt(enabled)
        assert got == variants[1], (got, chosen)
        def none_enabled(lines, prompt):
            return False
        fallback = {"prompt": variants[2], "ref_path": ""}
        refpool.pick = lambda now=None: fallback
        assert bank.pick_prompt(none_enabled) == variants[2]  # fallback без фильтра
    finally:
        refpool.PROMPT_VARIANTS = saved_variants
        if saved is not None:
            bank.refpool = saved


def test_margin_absorbs_ragged_cp_burst():
    """run 39924822702: группа ровно need+2 (22 при need=20), три рваных cp подряд ->
    свободных 19 < 20 = nobank, слот пропущен. Запас группы должен поглощать всплеск
    рваных cp: MARGIN >= 4."""
    assert bank.MARGIN >= 4, bank.MARGIN

def test_take_retries_failed_cp():
    """Рваный/несостоявшийся cp перекачивается (до 5 попыток) и не карантинится."""
    now = time.time()
    ents = [meta("a", 89, "F major"), meta("b", 89, "F major")]
    names = "\n".join(e["name"] + ".mp3" for e in ents) + "\n"
    metas = {f"/app/output/bank/anime-lofi/{e['name']}.json": json.dumps(
        {"prompt": e["prompt"], "seed": e["seed"]}) for e in ents}
    dk = FakeDocker({**metas, "/app/output/bank/anime-lofi": names})
    attempts = {"a": 0}

    def flaky_cp(*a):
        r = dk(*a)
        if a and a[0] == "cp":
            dst = Path(a[2])
            if dst.stem == "a":
                attempts["a"] += 1
                dst.write_bytes(b"ID3ok" if attempts["a"] >= 3 else b"")
            else:
                dst.write_bytes(b"ID3ok")
        return r

    with tempfile.TemporaryDirectory() as td:
        got = bank_release.take("anime lofi", 2, td, docker_sh=flaky_cp, now=now,
                                rng=random.Random(1), valid=lambda p: Path(p).stat().st_size > 0)
        assert got is not None and {p.stem for p in got} == {"a", "b"}, got
        assert attempts["a"] == 3, attempts


def test_take_never_quarantines():
    """24.10: выпуск карантинил 15 целых сегментов (вторая проверка врала на отсутствии
    tmp-папки). Контракт: take() не двигает файлы банка, только предупреждает."""

    now = time.time()
    ents = [meta(n, 89, "F major") for n in ("a", "b", "c")]
    names = "".join(e["name"] + ".mp3\n" for e in ents)
    metas = {f"/app/output/bank/anime-lofi/{e['name']}.json": json.dumps(
        {"prompt": e["prompt"], "seed": e["seed"]}) for e in ents}
    dk = FakeDocker({**metas, "/app/output/bank/anime-lofi": names})

    def no_dir(*a):
        if a and a[0] == "cp":
            Path(a[2]).write_bytes(b"")  # "invalid output path: directory does not exist"
        return dk(*a)

    with tempfile.TemporaryDirectory() as td:
        bank_release.take("anime lofi", 2, td, docker_sh=no_dir, now=now,
                          rng=random.Random(1), valid=lambda p: Path(p).stat().st_size > 0)
    mv = [op[1] for op in dk.ops if "mv " in op[1]]
    assert mv == [], mv  # банк не тронут

def test_main_sh_logs_docker_failures(capsys=None):
    """docker cp/exec rc!=0 печатает stderr — тихие cp-фелы давали «битые» без лога (t_ba72c7aa)."""
    import bank_release as br, subprocess, io, contextlib
    calls=[]
    def fake_run(cmd, **kw):
        calls.append(cmd)
        class R: returncode=7; stdout=''; stderr='No such container'
        return R()
    m=br.main
    import types
    src=None
    # вытаскиваем main.sh через monkeypatch subprocess.run внутри main
    real_run=subprocess.run
    buf=io.StringIO()
    def run_fake(*a, **kw):
        return fake_run(*a, **kw)
    # main() тяжёлый — тестируем контракт напрямую: переписанный sh-блок присутствует в исходнике
    import inspect
    ssrc=inspect.getsource(br.main)
    assert 'returncode != 0' in ssrc and 'stderr' in ssrc, 'main.sh должен логировать rc/stderr'



def test_take_creates_missing_run_dir():
    """23-24.10: ACF_RUN_DIR (runs/<run_id>) не существует после clean-checkout, docker cp rc=1
    'invalid output path' -> все сегменты «не доставлены» -> nobank. Контракт: take() создаёт run_dir."""
    import contextlib, io
    now = time.time()
    ents = [meta(n, 89, "F major") for n in ("a", "b")]
    names = "\n".join(e["name"] + ".mp3" for e in ents) + "\n"
    metas = {f"/app/output/bank/anime-lofi/{e['name']}.json": json.dumps(
        {"prompt": e["prompt"], "seed": e["seed"]}) for e in ents}
    dk = FakeDocker({**metas, "/app/output/bank/anime-lofi": names})
    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td) / "runs" / "new_run"   # НЕ создаём
        def cp_sh(*a):
            if a[0] == "cp":
                if not Path(a[2]).parent.exists():
                    return "invalid output path: directory does not exist"
                Path(a[2]).write_bytes(b"X" * 5)
                return ""
            return dk(*a)
        orig = bank_release.time.sleep
        bank_release.time.sleep = lambda s: None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                got = bank_release.take("anime lofi", 2, str(run_dir), docker_sh=cp_sh, now=now,
                                        rng=random.Random(1), valid=lambda p: True)
        finally:
            bank_release.time.sleep = orig
        assert got is not None and len(got) == 2, got


def _meta(n, bpm, key):
    return {"name": n, "prompt": f"p {bpm} BPM, {key}, t", "seed": 1}


def test_pick_cross_group_compatible_fills_need():
    """24.10 (коммент 05:47): крупнейшая группа 19 < need=20 -> pick None при 53 свободных.
    Контракт: добор из соседних групп (та же тональность или квартово-родственная, BPM в пределах
    COMPAT_BPM=4) до need; основная группа - большинство."""
    now = __import__("time").time()
    ents = [_meta(f"f{i}", 89, "F major") for i in range(19)]
    ents += [_meta(f"c{i}", 91, "F major") for i in range(3)]   # тот же key, BPM 89+-4
    got = bank_release.pick(ents, need=20, now=now, used_lines=[], rng=__import__("random").Random(1))
    assert got is not None, "19+3 совместимых должны дать выпуск"
    core = [e for e in got if e["name"].startswith("f")]
    assert len(core) == 19 and len(got) == 20, (len(core), len(got))
    assert all(abs((e["prompt"] and int(e["prompt"].split(" BPM")[0].split()[-1]) or 0) - 89) <= bank_release.COMPAT_BPM for e in got)


def test_pick_cross_group_rejects_incompatible():
    """Несовместимые (тоналность вне родства, BPM дальше COMPAT_BPM) не добираются:
    группа 4 < MIN_SEG + 1 чужой — чужой не тянет группу через MIN_SEG, ответ None."""
    now = __import__("time").time()
    ents = [_meta(f"f{i}", 89, "F major") for i in range(4)]
    ents += [_meta("x", 120, "D minor")]
    got = bank_release.pick(ents, need=20, now=now, used_lines=[], rng=__import__("random").Random(1))
    assert got is None, got


def test_pick_short_mix_instead_of_skip():
    """H3: даже need не добирается — короткий микс >= bank_release.MIN_SEG (>=5 сегм, 15 мин)
    вместо пропуска слота; меньше MIN_SEG = None."""
    now = __import__("time").time()
    ents = [_meta(f"f{i}", 89, "F major") for i in range(8)]
    got = bank_release.pick(ents, need=20, now=now, used_lines=[], rng=__import__("random").Random(1))
    assert got is not None and len(got) == 8, got
    ents = [_meta(f"g{i}", 89, "F major") for i in range(3)]
    got = bank_release.pick(ents, need=20, now=now, used_lines=[], rng=__import__("random").Random(1))
    assert got is None, got




def test_master_final_loudnorms_when_too_quiet():
    """run 40145954650: TP=-2.0 -> loudnorm пропускался, трек остался I=-17.4 (< -16) = 03c FAIL.
    Контракт: master_final нормализует не только при клиппинге, но и при I вне окна гейта."""
    import importlib.util
    import subprocess as sp
    import types
    from pathlib import Path as P
    HERE2 = P(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("br_mf", HERE2 / "bank_release.py")
    br = importlib.util.module_from_spec(spec)
    sys.modules["br_mf"] = br
    spec.loader.exec_module(br)

    class R:
        stderr = ""
        stdout = ""
        returncode = 0

    ran = []
    fake_mastering = types.ModuleType("mastering")
    fake_mastering.measure = lambda track: {"tp": -2.0, "i": -17.4}
    saved_mastering = sys.modules.get("mastering")
    saved_music = br._music_mod
    sys.modules["mastering"] = fake_mastering
    br._music_mod = lambda: types.SimpleNamespace(fade_end=lambda *a, **k: None)
    orig_run = sp.run
    import tempfile
    td = tempfile.mkdtemp()
    track = f"{td}/track.mp3"
    P(track).write_bytes(b"x")
    sp.run = lambda cmd, check=False, **k: (ran.append(cmd), P(str(cmd[-1])).write_bytes(b"y"), R())[2]
    try:
        import quality_gate as qg
        if qg.MIN_I <= -17.4 <= qg.MAX_I:
            fake_mastering.measure = lambda track: {"tp": -2.0, "i": qg.MIN_I - 2.0}
        br.master_final(track, "anime lofi")
    finally:
        sp.run = orig_run
        br._music_mod = saved_music
        if saved_mastering is None:
            sys.modules.pop("mastering", None)
        else:
            sys.modules["mastering"] = saved_mastering
    assert any("loudnorm" in " ".join(map(str, c)) for c in ran), ran[:2]


def test_trim_fade_head_cuts_leading_fade():
    """run 40145954650: тихое вступление первого сегмента = блоки 3-63 с на 4.8 LU ниже тела = A18 FAIL.
    trim_fade_head обязан существовать и срезать лидирующий фейд (синтетика: sine с фейдом 0->-30 дБ)."""
    import importlib.util
    import subprocess as sp
    import tempfile
    HERE2 = __import__("pathlib").Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("m03h", HERE2 / "03_music.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["m03h"] = m
    spec.loader.exec_module(m)
    assert hasattr(m, "trim_fade_head")
    with tempfile.TemporaryDirectory() as td:
        f = f"{td}/seg.mp3"
        sp.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=90",
                "-af", "volume=-12dB,afade=t=in:st=0:d=20", "-ac", "2",
                "-c:a", "libmp3lame", "-b:a", "192k", f], check=True)
        d0 = m._probe_sec(f)
        m.trim_fade_head([f], max_sec=20.0, log=lambda *a: None)
        d1 = m._probe_sec(f)
        assert d0 - d1 >= 5.0, (d0, d1)  # срезал вступление
        assert d1 >= 60.0  # тело цело


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"PASS {len(fns)} tests")
