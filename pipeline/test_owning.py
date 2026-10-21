#!/usr/bin/env python3
"""Self-check канала S1 ch1 «Economics of Owning» (@OwningItMath): ротация, скрипт, метаданные.
Запуск: python3 pipeline/test_owning.py (без сети, без ffmpeg/TTS)."""
import importlib.util
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import owning_channel as oc

_spec = importlib.util.spec_from_file_location("publish", Path(__file__).parent / "05_publish.py")
pub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pub)

GOOD = {
    "title": "The Economics of Owning a Car Wash",
    "hook": "A car wash can clear $20,000 a month. Here's the catch.",
    "beats": [
        {"say": "A single express tunnel costs about four million dollars to build.", "big": "$4M", "label": "build cost"},
        {"say": "On a good day it washes four hundred cars at twelve dollars each.", "big": "400", "label": "cars per day"},
        {"say": "That's nearly five thousand dollars a day before a single bill is paid.", "big": "$4.8K", "label": "daily revenue"},
        {"say": "Then come water, chemicals, power, and a loan payment that never sleeps.", "big": "$38K", "label": "monthly costs"},
        {"say": "Most owners keep twenty to thirty percent, and rainy months hurt.", "big": "25%", "label": "net margin"},
        {"say": "Memberships are the real business: recurring cash, rain or shine.", "big": "60%", "label": "revenue from members"},
    ],
    "description": "What it really costs to own a car wash, and where the profit hides.",
    "tags": ["car wash business", "small business", "passive income"],
}


def test_rotation_varies_topic_hook_structure():
    with tempfile.TemporaryDirectory() as td:
        picks = [oc.next_plan(Path(td)) for _ in range(len(oc.TOPICS))]
    combos = {(p["topic"], p["hook"], p["structure"]) for p in picks}
    assert len(combos) == len(picks), "комбинации повторились внутри цикла тем"
    assert len({p["topic"] for p in picks}) == len(oc.TOPICS), "темы повторились до полного цикла"
    # соседние видео отличаются и хуком, и структурой (inauthentic-content policy)
    for a, b in zip(picks, picks[1:]):
        assert a["hook"] != b["hook"] and a["structure"] != b["structure"], (a, b)
    for need in ("car wash", "laundromat", "vending route", "self-storage"):
        assert any(need in t for t in oc.TOPICS), need
    assert any("small-town" in t or "small town" in t for t in oc.TOPICS)


def test_prompt_carries_plan():
    plan = {"topic": "laundromat", "hook": oc.HOOKS[0], "structure": oc.STRUCTURES[0]}
    text = oc.idea_prompt(plan)
    for v in plan.values():
        assert v in text
    assert "JSON" in text and "Economics of Owning" in text


def test_validate_script():
    assert oc.validate_script(dict(GOOD)) is not None
    bad = dict(GOOD, beats=GOOD["beats"][:2])
    try:
        oc.validate_script(bad)
        raise AssertionError("короткий скрипт должен отклоняться")
    except ValueError:
        pass
    try:
        oc.validate_script(dict(GOOD, title="Car wash money"))
        raise AssertionError("заголовок без формата Owning должен отклоняться")
    except ValueError:
        pass
    long = dict(GOOD, beats=GOOD["beats"] * 4)
    try:
        oc.validate_script(long)
        raise AssertionError(">60с речи для Shorts должно отклоняться")
    except ValueError:
        pass


def test_parse_llm_json_fenced():
    raw = "```json\n{\"a\": 1}\n```"
    assert oc.parse_json(raw) == {"a": 1}


def test_cta_decision_and_description():
    d = oc.short_description(GOOD)
    assert "Not financial advice" in d and "#Shorts" in d
    assert oc.AI_NOTE in d
    # решение владельца 18.10 (t_018254ae): таро-CTA с канала 1 убрать везде — аудитория не та,
    # вредит доверию; на канале 1 только тематические ссылки. Таро-воронка → канал 2.
    ch = oc.channel_description()
    for text in (d, ch):
        assert "tarot" not in text.lower() and "t.me/" not in text
    assert "https://" in ch and oc.DISCLAIMER in ch


def test_upload_body_for_channel():
    idea = dict(GOOD, channel="owning")
    body = pub.build_body(idea, {})
    sn, st = body["snippet"], body["status"]
    assert sn["categoryId"] == "27"  # Education, не Music
    assert sn["title"].startswith("The Economics of Owning")
    assert "#Shorts" in sn["description"] and "#lofi" not in sn["description"]
    assert st["containsSyntheticMedia"] is True and st["privacyStatus"] == "public"
    # lofi-путь не сломан
    lofi = pub.build_body({"title": "Rainy Night Lofi Beats", "description": "x", "tags": []}, {"duration": 900})
    assert lofi["snippet"]["categoryId"] == "10" and "#lofi" in lofi["snippet"]["description"]


def test_count_today():
    import datetime as dt
    ts = ["2026-10-18T15:00:01Z", "2026-10-18T21:00:00Z", "2026-10-17T21:00:00Z", ""]
    assert oc.count_today(ts, dt.date(2026, 10, 18)) == 2


def test_tts_retries_transient_failure():
    """run 39659160544: edge_tts NoAudioReceived (сбой сервиса) уронил выпуск — повтор, не падение."""
    import subprocess as sp
    n = {"tts": 0}

    def fake(cmd, **k):
        if "edge_tts" in cmd:
            n["tts"] += 1
            if n["tts"] < 3:
                raise sp.CalledProcessError(1, cmd)
            return sp.CompletedProcess(cmd, 0, "", "")
        return sp.CompletedProcess(cmd, 0, "1.5\n", "")
    orig, oc.subprocess.run = oc.subprocess.run, fake
    try:
        assert oc.tts("hi", Path("x.mp3"), sleep=lambda s: None) == 1.5 and n["tts"] == 3
    finally:
        oc.subprocess.run = orig


if __name__ == "__main__":
    test_tts_retries_transient_failure()
    test_count_today()
    test_rotation_varies_topic_hook_structure()
    test_prompt_carries_plan()
    test_validate_script()
    test_parse_llm_json_fenced()
    test_cta_decision_and_description()
    test_upload_body_for_channel()
    print("all owning tests passed")
