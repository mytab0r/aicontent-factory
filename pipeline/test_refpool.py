#!/usr/bin/env python3
"""t_d53850f6: пул эталонов + ротация промпта по дню.

RED-история: до карточки пул = один файл ACE15_REF_AUDIO (ref1) и один промпт
GENRE_PROMPTS["anime lofi"] — все выпуски одного вкуса. Тест фиксирует:
пул >= 8, соседние дни различаются, выбор детерминирован, промпт-гигиена.
"""
import datetime as dt
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("rp", Path(__file__).parent / "refpool.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

UTC = dt.timezone.utc


def test_pool_size_in_range():
    assert 8 <= len(rp.POOL) <= 12, f"пул {len(rp.POOL)} вне 8-12"


def test_pool_refs_distinct():
    ids = [e[0] for e in rp.POOL]
    assert len(ids) == len(set(ids)), "дубликаты эталонов в пуле"


def test_pick_deterministic_and_rotates_daily():
    base = dt.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    a = rp.pick(base)
    b = rp.pick(base)
    assert a == b, "выбор по дню должен быть детерминированным"
    nxt = rp.pick(base + dt.timedelta(days=1))
    assert (nxt["yt_id"], nxt["prompt"]) != (a["yt_id"], a["prompt"]), "соседние дни совпали полностью"
    # за цикл пула каждый эталон выпадает ровно раз
    seen = [rp.pick(base + dt.timedelta(days=i))["yt_id"] for i in range(len(rp.POOL))]
    assert sorted(seen) == sorted(e[0] for e in rp.POOL)


def test_prompt_rotates_and_differs():
    base = dt.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    prompts = [rp.pick(base + dt.timedelta(days=i))["prompt"] for i in range(len(rp.PROMPT_VARIANTS))]
    assert len(set(prompts)) == len(rp.PROMPT_VARIANTS), "промпты соседних дней совпадают"


def test_prompt_hygiene_no_noise_words_no_vocals():
    bad = ["vinyl", "crackle", "tape hiss", "grit", "noise", "minor"]
    for p in rp.PROMPT_VARIANTS:
        low = p.lower()
        assert not any(w in low for w in bad), f"noise/minor в промпте: {p!r}"
        assert "no vocals" in low, f"нет 'no vocals': {p!r}"


def test_prompts_are_owner_approved_family():
    """t_ef393676: ротация = только семейство ab_1/ab_3 (одобрены 20.10). music box (ab_0)
    и harp (ab_2) без оценки владельца -> не в ротации; темп 64-72 (25.10 владелец: 89 «слишком энергично»)."""
    import re
    for p in rp.PROMPT_VARIANTS:
        low = p.lower()
        assert low.startswith("dreamy lofi chillout instrumental"), p
        assert "glockenspiel" in low or "celesta" in low, f"нет колокольчиков: {p!r}"
        assert not any(w in low for w in ("music box", "harp", "anime lofi")), p
        assert int(re.search(r"(\d+) BPM", p).group(1)) in range(64, 73), p


def test_ref_fragment_not_from_zero():
    assert rp.REF_START_SEC >= 60, "фрагмент с 0:00 = самый fingerprint-опасный кусок"


def test_claim_bumps_refpool_offset():
    import tempfile
    now = dt.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as td:
        rp.OFFSET_FILE = Path(td) / "off.txt"
        a = rp.pick(now)
        rp.bump_offset()
        b = rp.pick(now)
        assert (b["yt_id"], b["prompt"]) != (a["yt_id"], a["prompt"]), "offset не сменил пару"


if __name__ == "__main__":
    test_pool_size_in_range()
    test_pool_refs_distinct()
    test_pick_deterministic_and_rotates_daily()
    test_prompt_rotates_and_differs()
    test_prompt_hygiene_no_noise_words_no_vocals()
    test_prompts_are_owner_approved_family()
    test_ref_fragment_not_from_zero()
    test_claim_bumps_refpool_offset()
    print("ok test_refpool")
