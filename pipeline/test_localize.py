#!/usr/bin/env python3
"""Self-check localize.py (ES/pt-BR localizations + субтитры, t_b9eb61b2). Без сети: фейковые YouTube и LLM.
Запуск: python3 pipeline/test_localize.py"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import localize as lz

_spec = importlib.util.spec_from_file_location("publish", Path(__file__).parent / "05_publish.py")
pub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pub)

CUES = [(0.0, 2.5, "A car wash can clear $20,000 a month."), (2.75, 5.0, "Here's the catch.")]
SRC = {"title": "The Economics of Owning a Car Wash", "description": "Real math.\n\n#Shorts #smallbusiness"}


def fake_translate(src: dict, lang: str) -> dict:
    tag = lang.upper()
    return {"title": f"[{tag}] {src['title']}", "description": f"[{tag}] {src['description']}",
            "lines": [f"[{tag}] {x}" for x in src["lines"]]}


class Exec:
    def __init__(self, v):
        self.v = v

    def execute(self):
        return self.v


class FakeYT:
    def __init__(self, caps=None, locs=None):
        self.caps = caps or []
        self.locs = locs if locs is not None else {"en": {"title": "t", "description": "d"}}
        self.calls = []

    def captions(self):
        yt = self

        class C:
            def list(self, **kw):
                return Exec({"items": [{"id": f"c{i}", "snippet": s} for i, s in enumerate(yt.caps)]})

            def insert(self, part, body, media_body):
                yt.calls.append(("captions.insert", body["snippet"]["language"], media_body))
                yt.caps.append({"language": body["snippet"]["language"], "trackKind": "standard"})
                return Exec({"id": "new"})

            def download(self, id, tfmt):
                return Exec(b"1\n00:00:00,080 --> 00:00:02,500\nHello there\nfriend\n\n2\n00:00:02,600 --> 00:00:04,000\nBye\n")
        return C()

    def videos(self):
        yt = self

        class V:
            def list(self, **kw):
                return Exec({"items": [{"id": kw["id"], "snippet": {"title": SRC["title"], "description": SRC["description"],
                                                                    "defaultLanguage": "en"}, "localizations": yt.locs}]})

            def update(self, part, body):
                yt.calls.append(("videos.update", part, body))
                yt.locs = body["localizations"]
                return Exec(body)
        return V()


def test_srt_format():
    s = lz.to_srt(CUES)
    assert s.startswith("1\n00:00:00,000 --> 00:00:02,500\nA car wash"), s
    assert "2\n00:00:02,750 --> 00:00:05,000\nHere's the catch.\n" in s
    assert lz.parse_srt(s) == [(0.0, 2.5, CUES[0][2]), (2.75, 5.0, CUES[1][2])]


def test_flag_off_is_noop():
    os.environ["LOCALIZE"] = "0"
    yt = FakeYT()
    assert lz.enabled() is False
    assert lz.localize_video(yt, "vid", CUES, translate=fake_translate) is None
    assert yt.calls == []
    # 05_publish: тело загрузки не меняется
    body = pub.build_body(dict(channel="owning", title=SRC["title"], description="x", tags=[]), {})
    assert "localizations" not in body


def test_flag_on_updates_and_inserts_both_langs():
    os.environ["LOCALIZE"] = "1"
    yt = FakeYT()
    res = lz.localize_video(yt, "vid", CUES, translate=fake_translate)
    upd = [c for c in yt.calls if c[0] == "videos.update"]
    assert len(upd) == 1 and upd[0][1] == "localizations"
    locs = upd[0][2]["localizations"]
    assert set(locs) == {"en", "es", "pt-BR"}, locs  # существующая en не теряется
    assert locs["es"]["title"].startswith("[ES]") and locs["pt-BR"]["description"].startswith("[PT-BR]")
    ins = sorted(c[1] for c in yt.calls if c[0] == "captions.insert")
    assert ins == ["es", "pt-BR"], ins
    assert res == {"localizations": ["es", "pt-BR"], "captions": ["es", "pt-BR"]}
    # повтор = идемпотентно: ни перевода, ни записи
    yt.calls.clear()
    assert lz.localize_video(yt, "vid", CUES, translate=None) == {"localizations": [], "captions": []}
    assert yt.calls == []


def test_backfill_uses_en_asr_track():
    os.environ["LOCALIZE"] = "1"
    yt = FakeYT(caps=[{"language": "en", "trackKind": "asr"}])
    cues = lz.source_cues(yt, "vid")
    assert cues == [(0.08, 2.5, "Hello there friend"), (2.6, 4.0, "Bye")], cues


def test_translation_validation():
    src = {"title": "T", "description": "D", "lines": ["a", "b"]}
    ok = {"title": "t" * 150, "description": "d", "lines": ["x", "y"]}
    out = lz.check_translation(src, ok)
    assert len(out["title"]) == 100
    for bad in ({"title": "t", "description": "d", "lines": ["x"]}, {"title": "", "description": "d", "lines": ["x", "y"]}):
        try:
            lz.check_translation(src, bad)
            raise AssertionError("невалидный перевод должен отклоняться")
        except ValueError:
            pass


def test_render_writes_cues():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "cues.json"
        lz.write_cues(p, [("a", 2.0), ("b", 1.5)], pad=0.25)
        assert json.loads(p.read_text()) == [[0.0, 1.75, "a"], [2.0, 3.25, "b"]]


if __name__ == "__main__":
    test_srt_format()
    test_flag_off_is_noop()
    test_flag_on_updates_and_inserts_both_langs()
    test_backfill_uses_en_asr_track()
    test_translation_validation()
    test_render_writes_cues()
    print("all localize tests passed")
