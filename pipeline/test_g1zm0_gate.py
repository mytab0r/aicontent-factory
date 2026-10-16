#!/usr/bin/env python3
"""Самопроверка g1zm0_gate.py (t_d53850f6): claim -> private + перегенерация, clean -> TG, approve -> public."""
import datetime as dt
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import g1zm0_gate as g  # noqa: E402
import g1zm0_rotation as rot  # noqa: E402


class YT:
    def __init__(self, items):
        self.items, self.updated = items, []

    def videos(self):
        return self

    def list(self, **kw):
        self._r = {"items": self.items.get(kw["id"], [])}
        return self

    def update(self, **kw):
        self._r = {}
        self.updated.append(kw["body"])
        return self

    def execute(self):
        return self._r


CLEAN = [{"status": {"uploadStatus": "processed"}, "contentDetails": {}}]
CLAIM = [{"status": {"uploadStatus": "processed"}, "contentDetails": {"licensedContent": True}}]
NOW = dt.datetime(2026, 10, 16, 12, tzinfo=dt.timezone.utc)

with tempfile.TemporaryDirectory() as td:
    sd, ad = Path(td) / "s", Path(td) / "a"
    meta = {"genre": "anime lofi", "rotation": {"day": "2026-10-16", "attempt": 0, "ref": "macleod_calmant"}}
    g.record("vClaim", "anime lofi", meta, sd, now=NOW - dt.timedelta(hours=3))
    g.record("vClean", "anime lofi", dict(meta, rotation=dict(meta["rotation"], day="2026-10-15")), sd,
             now=NOW - dt.timedelta(hours=3))
    g.record("vYoung", "anime lofi", dict(meta, rotation=dict(meta["rotation"], day="2026-10-14")), sd,
             now=NOW - dt.timedelta(minutes=30))
    assert g.pending_today("anime lofi", dt.date(2026, 10, 16), sd)
    assert g.pending_today(None, dt.date(2026, 10, 16), sd)
    assert not g.pending_today("chill phonk", dt.date(2026, 10, 16), sd)

    yt = YT({"vClaim": CLAIM, "vClean": CLEAN, "vYoung": CLEAN})
    disp, msgs, pub = [], [], []
    items = g.step(g.load(sd), yt, NOW, lambda *a: disp.append(a), msgs.append, lambda *a: pub.append(a), ad)
    g.save(items, sd)
    st = {e["video_id"]: e["status"] for e in g.load(sd)}
    assert st == {"vClaim": "claimed", "vClean": "await_approval", "vYoung": "pending"}, st
    assert disp == [("anime lofi", "2026-10-16", 1)], disp  # перегенерация с attempt+1
    assert yt.updated[0] == {"id": "vClaim", "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}}
    assert any("studio.youtube.com/video/vClean/copyright" in m for m in msgs)
    # claim закрыл день -> guard пускает перегенерацию; ни одного public без одобрения
    assert not g.pending_today("anime lofi", dt.date(2026, 10, 16), sd)
    assert not pub

    # повторный проход: без одобрения TG не дублируется
    n = len(msgs)
    g.save(g.step(g.load(sd), yt, NOW, lambda *a: disp.append(a), msgs.append, lambda *a: pub.append(a), ad), sd)
    assert len(msgs) == n and not pub

    # одобрение -> public + плейлист
    rot.approve(ad, "vClean")
    g.save(g.step(g.load(sd), yt, NOW, lambda *a: disp.append(a), msgs.append, lambda *a: pub.append(a), ad), sd)
    assert pub == [("vClean", "anime lofi")] and yt.updated[-1]["status"]["privacyStatus"] == "public"
    assert {e["video_id"]: e["status"] for e in g.load(sd)}["vClean"] == "public"

    # последняя попытка с claim -> blocked, без dispatch
    g.record("vLast", "anime lofi", dict(meta, rotation=dict(meta["rotation"], attempt=g.MAX_ATTEMPTS - 1)), sd,
             now=NOW - dt.timedelta(hours=3))
    yt.items["vLast"] = CLAIM
    d0 = len(disp)
    g.save(g.step(g.load(sd), yt, NOW, lambda *a: disp.append(a), msgs.append, lambda *a: pub.append(a), ad), sd)
    assert {e["video_id"]: e["status"] for e in g.load(sd)}["vLast"] == "blocked" and len(disp) == d0

# атрибуция CC BY и ротация эталона: attempt сдвигает эталон
assert "CC BY 3.0" in rot.REF_CREDIT("macleod_calmant")
d = dt.date(2026, 10, 16)
assert rot.pick_ref(d, 0) != rot.pick_ref(d, 1)
print("test_g1zm0_gate OK")

# ---- интеграция 03_music.main: ротация эталона/промпта по дню попадает в генератор и music_meta ----
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

spec = importlib.util.spec_from_file_location("music", Path(__file__).parent / "03_music.py")
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)
with tempfile.TemporaryDirectory() as td:
    run, refs = Path(td) / "run", Path(td) / "refs"
    run.mkdir(); refs.mkdir()
    (run / "idea.json").write_text('{"mood": "cozy lofi"}')
    want = rot.pick_ref(dt.date(2026, 10, 16), 1)
    (refs / f"{want}.wav").write_bytes(b"x")
    calls = []
    music.latest_run_dir = lambda: run
    music.generate_track_v15 = lambda p, d, s, out, **kw: (calls.append((p, kw)), Path(out).write_bytes(b"x"))
    music.mastering.master = lambda *a: None
    rot.REF_DIR = refs
    os.environ.update(G1ZM0_GATE="1", G1ZM0_DAY="2026-10-16", G1ZM0_ATTEMPT="1", GENRE="anime lofi",
                      ACE15_ENDPOINT="http://stub", TRACK_DURATION_SEC="60")
    try:
        music.main()
    finally:
        for k in ("G1ZM0_GATE", "G1ZM0_DAY", "G1ZM0_ATTEMPT", "GENRE", "ACE15_ENDPOINT", "TRACK_DURATION_SEC"):
            os.environ.pop(k)
    m = json.loads((run / "music_meta.json").read_text())
    p = rot.pick_prompt(dt.date(2026, 10, 16), 1)
    assert m["ref"] == want and m["rotation"]["attempt"] == 1, m
    assert calls[0][1] == {"ref_audio": str(refs / f"{want}.wav"), "bpm": p["bpm"], "key": p["key"]}, calls
    assert p["instrument"] in calls[0][0] and music.GENRE_PROMPTS["anime lofi"] in calls[0][0]
print("test_g1zm0_gate main OK")
