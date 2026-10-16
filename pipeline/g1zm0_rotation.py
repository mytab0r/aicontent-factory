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
# 10 слотов (8-12). Только CC BY 3.0 (Kevin MacLeod, Wikimedia Commons): чужой OST под
# копирайтом не используем (юр. риск + Content ID). slug -> (файл Commons, старт среза, с).
# Атрибуция обязательна: REF_CREDIT(slug) в описание видео. Детали: refs/LICENSES.md.
REF_SOURCES = {
    "macleod_clean_soul": ("File:Kevin MacLeod - Clean Soul.ogg", 30),
    "macleod_smoother_move": ("File:Kevin MacLeod - Smoother Move.ogg", 30),
    "macleod_dream_culture": ("File:Kevin MacLeod - Dream Culture.ogg", 30),
    "macleod_inner_light": ("File:Kevin MacLeod - Inner Light.ogg", 60),
    "macleod_autumn_day": ("File:Kevin MacLeod - Autumn Day.ogg", 30),
    "macleod_silver_blue_light": ("File:Kevin MacLeod - Silver Blue Light.ogg", 60),
    "macleod_carefree": ("File:Kevin MacLeod - Carefree.ogg", 30),
    "macleod_calmant": ("File:Kevin MacLeod - Calmant.ogg", 30),
    "macleod_windswept": ("File:Kevin MacLeod - Windswept.ogg", 30),
    "macleod_early_riser": ("File:Kevin MacLeod - Early Riser.ogg", 30),
}
REF_POOL = list(REF_SOURCES)


def REF_CREDIT(slug: str) -> str:
    t = REF_SOURCES[slug][0].removeprefix("File:Kevin MacLeod - ").removesuffix(".ogg")
    return f'Style reference: "{t}" by Kevin MacLeod (incompetech.com), CC BY 3.0 https://creativecommons.org/licenses/by/3.0/'


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


def yt_claim_status(youtube, video_id: str) -> str:
    """YouTube videos.list -> 'pending'|'claimed'|'clean'.
    claim: contentDetails.licensedContent=True (Content ID match) или rejectionReason claim/copyright."""
    items = youtube.videos().list(part="status,contentDetails,processingDetails", id=video_id).execute().get("items", [])
    if not items:
        return "pending"
    it = items[0]
    st = it.get("status", {})
    if st.get("rejectionReason") in ("claim", "copyright") or it.get("contentDetails", {}).get("licensedContent"):
        return "claimed"
    if st.get("uploadStatus") != "processed" or it.get("processingDetails", {}).get("processingStatus") not in (None, "succeeded"):
        return "pending"
    return "clean"


def upload_unlisted(youtube, path: str, title: str):
    """Загрузка ТОЛЬКО unlisted (никогда public) для Content ID пре-чека.
    None = uploadLimitExceeded: слот пропущен, одно TG-сообщение, файл не тронут."""
    from googleapiclient.http import MediaFileUpload
    body = {"snippet": {"title": title[:100], "categoryId": "10"},
            "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": True}}
    req = youtube.videos().insert(part="snippet,status", body=body,
                                  media_body=MediaFileUpload(path, resumable=True, chunksize=4 << 20))
    resp = None
    try:
        while resp is None:
            _, resp = req.next_chunk(num_retries=5)
    except Exception as e:
        # дневной лимит загрузок канала (общий с daily-video): слот пропускаем, файл не трогаем
        if b"uploadLimitExceeded" not in (getattr(e, "content", None) or b""):
            raise
        from common import tg_send
        tg_send(f"⏸ YouTube uploadLimitExceeded: {Path(path).name} не загружен, повтор в следующем слоте")
        return None
    return resp["id"]


def wait_claim(youtube, video_id: str, tries: int = 24, delay: int = 300, sleep=None) -> str:
    """Ждёт результат Content ID (до tries*delay с; clean считается стабильным после 2 подряд)."""
    import time
    sleep = sleep or time.sleep
    clean = 0
    for _ in range(tries):
        st = yt_claim_status(youtube, video_id)
        if st == "claimed":
            return st
        clean = clean + 1 if st == "clean" else 0
        if clean >= 2:
            return "clean"
        sleep(delay)
    return "pending"


def publish_if_approved(youtube, video_id: str, track_id: str, marker_dir: Path) -> bool:
    """unlisted -> public только при clean + approve(); иначе False, ничего не меняется."""
    if not (Path(marker_dir) / f"{track_id}.approved").exists():
        return False
    if yt_claim_status(youtube, video_id) != "clean":
        return False
    youtube.videos().update(part="status", body={"id": video_id, "status": {
        "privacyStatus": "public", "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": True}}).execute()
    return True


if __name__ == "__main__":
    import tempfile
    # пул
    assert 8 <= len(REF_POOL) <= 12 and len(set(REF_POOL)) == len(REF_POOL)
    assert all("MacLeod" in REF_CREDIT(r) for r in REF_POOL)
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
    # YouTube-обвязка на фейке
    class Fake:
        def __init__(s, items): s.items, s.updated = items, []
        def videos(s): return s
        def list(s, **k): s.k = k; return s
        def update(s, **k): s.updated.append(k); return s
        def execute(s): return {"items": s.items(), "x": 1} if callable(s.items) else {"items": s.items}
    ok = {"status": {"uploadStatus": "processed"}, "contentDetails": {}}
    assert yt_claim_status(Fake([ok]), "v") == "clean"
    assert yt_claim_status(Fake([{**ok, "contentDetails": {"licensedContent": True}}]), "v") == "claimed"
    assert yt_claim_status(Fake([{"status": {"uploadStatus": "uploaded"}}]), "v") == "pending"
    assert wait_claim(Fake([ok]), "v", tries=3, delay=0, sleep=lambda d: None) == "clean"
    assert wait_claim(Fake([{"status": {}}]), "v", tries=2, delay=0, sleep=lambda d: None) == "pending"
    with tempfile.TemporaryDirectory() as td:
        y = Fake([ok])
        assert not publish_if_approved(y, "v", "t9", td) and not y.updated  # без одобрения
        approve(td, "t9")
        yc = Fake([{**ok, "contentDetails": {"licensedContent": True}}])
        assert not publish_if_approved(yc, "v", "t9", td) and not yc.updated  # claim
        assert publish_if_approved(y, "v", "t9", td) and y.updated[0]["body"]["status"]["privacyStatus"] == "public"
    print("OK")
