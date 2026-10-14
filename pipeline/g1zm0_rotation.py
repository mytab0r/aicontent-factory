#!/usr/bin/env python3
"""Ротация эталонов/промптов + гейт Content ID + A/B (карточка t_d53850f6).

Чистая логика без сети: аплоад/ACE вызываются снаружи. Cover/ремикс чужих
треков запрещён в коде (CoverModeError). Публикация только после одобрения.
ponytail: пул из 10 ID-слотов; файлы 90с кладутся в REF_DIR вручную после
A/B-одобрения (непроверенные эталоны в прод не идут). Расширять — добавлением строки.
"""
import datetime as dt
import os
from pathlib import Path

REF_DIR = Path(os.environ.get("G1ZM0_REF_DIR", "refs"))
REF_SECONDS = 90
# 10 слотов (8-12). Первый = одобренный K/DA Seraphine; остальные кандидаты (OST).
REF_POOL = [
    "kda_seraphine", "persona5_last_surprise", "genshin_liyue", "nier_weight_of_the_world",
    "stardew_valley_overture", "zelda_botw_main", "your_name_sparkle", "hades_good_riddance",
    "celeste_resurrections", "sonic_mania_studiopolis",
]
INSTRUMENTS = ["rhodes piano", "plucked synth", "soft bells", "clean electric guitar", "marimba", "airy flute synth"]
TEMPOS = [85, 90, 95, 100, 105]
KEYS = ["C major", "G major", "F major", "D major", "A major", "E-flat major"]
BANNED = ("vinyl", "hiss", "crackle", "grit", "noise", " minor")
BASE = "dreamy lofi chillout, lush synth pads, deep sub bass, groovy drums, bright clean mix, instrumental, no vocals"


class CoverModeError(RuntimeError):
    pass


def enable_cover_mode(*_, **__):
    raise CoverModeError("cover/remix чужих треков запрещён (Content ID)")


def _day(d) -> int:
    return d.toordinal() if isinstance(d, (dt.date,)) else int(d)


def pick_ref(day, attempt: int = 0) -> str:
    """Эталон: индекс = день % размер пула; attempt сдвигает при перегенерации."""
    return REF_POOL[(_day(day) + attempt) % len(REF_POOL)]


def pick_prompt(day, attempt: int = 0) -> dict:
    """Взаимно-простые шаги (1/2/3 по циклам 6/5/6 не гарантируют) -> сверяем тестом."""
    n = _day(day) + attempt
    p = dict(instrument=INSTRUMENTS[n % 6], bpm=TEMPOS[n % 5], key=KEYS[(n // 5) % 6])
    p["prompt"] = f"{BASE}, {p['instrument']} melody, {p['key']}, {p['bpm']} BPM"
    return p


def ab_samples(day) -> list[dict]:
    """4 сэмпла на 4 разных эталонах -> владельцу. Прод только после approve()."""
    return [{"ref": pick_ref(day, i), **pick_prompt(day, i)} for i in range(4)]


def approve(marker_dir: Path, track_id: str) -> None:
    Path(marker_dir).mkdir(parents=True, exist_ok=True)
    (Path(marker_dir) / f"{track_id}.approved").write_text("ok")


def content_id_gate(day, track_id, generate, upload_private, claim_status,
                    marker_dir: Path, max_attempts: int = 4) -> dict:
    """generate(ref, prompt)->path; upload_private(path)->video_id (unlisted/private);
    claim_status(video_id)->'clean'|'claimed'|'pending' (ждёт — вызывающий опрашивает).
    clean + одобрение владельца => publishable. claim => перегенерация с другим эталоном."""
    for a in range(max_attempts):
        ref, prm = pick_ref(day, a), pick_prompt(day, a)
        vid = upload_private(generate(ref, prm["prompt"]))
        st = claim_status(vid)
        if st == "pending":
            return {"state": "waiting", "video_id": vid, "attempt": a}
        if st == "clean":
            ok = (Path(marker_dir) / f"{track_id}.approved").exists()
            return {"state": "publishable" if ok else "await_owner_approval",
                    "video_id": vid, "ref": ref, "attempt": a}
    return {"state": "blocked_all_claimed"}


if __name__ == "__main__":
    import tempfile
    # пул
    assert 8 <= len(REF_POOL) <= 12 and len(set(REF_POOL)) == len(REF_POOL)
    # соседние дни различаются и по эталону, и по промпту
    d0 = dt.date(2026, 10, 14)
    for i in range(60):
        a, b = d0 + dt.timedelta(i), d0 + dt.timedelta(i + 1)
        assert pick_ref(a) != pick_ref(b)
        assert pick_prompt(a) != pick_prompt(b)
        assert pick_prompt(a) == pick_prompt(a)  # детерминизм
    # гигиена промптов
    for i in range(400):
        p = pick_prompt(i)["prompt"].lower()
        assert not any(w in p for w in BANNED), p
    # A/B: 4 разных эталона
    assert len({s["ref"] for s in ab_samples(d0)}) == 4
    # cover запрещён
    try:
        enable_cover_mode(); raise SystemExit("cover не запрещён")
    except CoverModeError:
        pass
    # гейт
    with tempfile.TemporaryDirectory() as td:
        refs_used = []
        gen = lambda r, p: refs_used.append(r) or r
        claims = iter(["claimed", "claimed", "clean"])
        res = content_id_gate(d0, "t1", gen, lambda p: p, lambda v: next(claims), td)
        assert res["state"] == "await_owner_approval" and res["attempt"] == 2
        assert len(set(refs_used)) == 3, "перегенерация должна менять эталон"
        approve(td, "t1")
        res = content_id_gate(d0, "t1", gen, lambda p: p, lambda v: "clean", td)
        assert res["state"] == "publishable"
        assert content_id_gate(d0, "t2", gen, lambda p: p, lambda v: "pending", td)["state"] == "waiting"
        assert content_id_gate(d0, "t3", gen, lambda p: p, lambda v: "claimed", td)["state"] == "blocked_all_claimed"
    print("OK")
