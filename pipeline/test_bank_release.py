#!/usr/bin/env python3
"""t_ba72c7aa R2: выпуск собирается ИЗ БАНКА (bank_release), не генерирует.
R4: статистика отказов по промптам (stats_record/fail_rate/prompt_enabled) в bank.py.
Тесты = контракт; реализация пишется по тому же контракту (TDD RED)."""
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


def test_take_copies_each_segment_or_none():
    now = time.time()
    ents = [meta("a", 89, "F major"), meta("b", 89, "F major")]
    names = "\n".join(e["name"] + ".mp3" for e in ents) + "\n"
    metas = {f"/app/output/bank/anime-lofi/{e['name']}.json": json.dumps(
        {"prompt": e["prompt"], "seed": e["seed"]}) for e in ents}
    dk = FakeDocker({**{f"/app/output/bank/anime-lofi/{e['name']}.mp3": b"x" for e in ents},
                     **metas, "/app/output/bank/anime-lofi": names})
    with tempfile.TemporaryDirectory() as td:
        got = bank_release.take("anime lofi", 2, td, docker_sh=dk, now=now, rng=random.Random(1))
        assert got is not None and len(got) == 2
        cps = [op for op in dk.ops if op[0][0] == "cp"]
        assert len(cps) == 2 and all(".mp3" in op[0][1] for op in cps), dk.ops
        assert bank_release.take("anime lofi", 5, td, docker_sh=dk, now=now, rng=random.Random(1)) is None


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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"PASS {len(fns)} tests")
