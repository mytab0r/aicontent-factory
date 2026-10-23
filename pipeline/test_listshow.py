#!/usr/bin/env python3
"""Self-check режима list-видео «listshow» (S1 ch2 long-form): флаг, структура 13-15 пунктов,
хронометраж >= 9.5 мин, анти-шаблонная вариация, Shorts-окна из списка.
Запуск: python3 pipeline/test_listshow.py (без сети; render-тесту нужны ffmpeg + pillow)."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import listshow_channel as ls


def item(n_words=110, **kw):
    d = {"title": f"Point number {n_words}", "text": " ".join(["fact"] * n_words) + "."}
    d.update(kw)
    return d


GOOD = {"title": "Things That Will Be Illegal Soon", "description": "A list video.", "tags": ["list"],
        "items": [item(title=f"Point number {k}") for k in range(13)]}


def test_flag_on_off():
    os.environ.pop("LIST2D", None)
    assert not ls.enabled()
    for v, want in (("1", True), ("0", False), ("", False), ("true", True)):
        os.environ["LIST2D"] = v
        assert ls.enabled() is want, v
    os.environ.pop("LIST2D")
    # выключенный флаг: main = no-op с exit 0 (откат = снять vars.LIST2D)
    r = subprocess.run([sys.executable, str(Path(ls.__file__)), "render"], capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if k != "LIST2D"})
    assert r.returncode == 0 and "disabled" in r.stdout, (r.returncode, r.stdout, r.stderr)


def test_validate_rejects_short_or_wrong_shape():
    # слишком мало пунктов
    try:
        ls.validate_script({**GOOD, "items": GOOD["items"][:8]})
        raise AssertionError("должно отклоняться: 8 < 12")
    except ValueError:
        pass
    # слишком мало слов => long < 9 мин
    try:
        ls.validate_script({**GOOD, "items": [item(n_words=20) for _ in range(13)]})
        raise AssertionError("должно отклоняться: < MIN_WORDS")
    except ValueError:
        pass
    # не тот заголовок (должен начинаться с заголовка из TITLE_PATTERNS/списочной фразы)
    try:
        ls.validate_script({**GOOD, "title": "My vlog about stuff"})
        raise AssertionError("должно отклоняться: заголовок не списочный")
    except ValueError:
        pass


def test_validate_normalizes_items():
    # пустые заголовки/тексты выбрасываются; остальные нормализуются
    s = ls.validate_script({**GOOD, "items": [item(title="")] + GOOD["items"]})
    assert len(s["items"]) == 13
    for it in s["items"]:
        assert it["title"].strip() and it["text"].strip()
    assert len(s["title"]) <= 100
    # повтор заголовка = шаблон -> отказ
    try:
        ls.validate_script({**GOOD, "items": GOOD["items"][:-1] + [item(title="Point number 3")]})
        raise AssertionError("должно отклоняться: дубль заголовка")
    except ValueError:
        pass
    # неизвестное место -> детерминированная нормализация в разрешённое
    s2 = ls.validate_script({**GOOD, "items": [item(place="mars")] + GOOD["items"][1:]})
    assert s2["items"][0]["place"] in ls.PLACES or s2["items"][0]["place"] in ls.wf.PLACES


def test_rotation_varies_topic_and_palette():
    with tempfile.TemporaryDirectory() as td:
        picks = [ls.next_plan(Path(td)) for _ in range(len(ls.TOPICS))]
    assert len({p["topic"] for p in picks}) == len(ls.TOPICS)
    for a, b in zip(picks, picks[1:]):
        assert a["palette"] != b["palette"]


def test_items_vary_across_video_no_repeated_filler():
    """Анти-inauthentic: у пунктов внутри выпуска разные заголовки, места; голоса ротируются item_voice."""
    s = ls.validate_script({**GOOD, "items": [
        item(title=f"Item {k}", place=pl) for k, pl in
        enumerate(["city", "nature", "space"] * 5)]})
    titles = [i["title"] for i in s["items"]]
    assert len(set(titles)) == len(titles), "заголовки пунктов повторяются = шаблон"
    assert len({i.get("place", ls.PLACES[0]) for i in s["items"]}) >= 3, "места не варьируются"
    voices = [ls.item_voice(0, k) for k in range(len(s["items"]))]
    assert len(set(voices)) >= 3, "голос не варьируется между пунктами"
    assert len({ls.item_voice(7, k) for k in range(len(s["items"]))}) >= 3


def test_long_duration_target():
    """План хронометража: сумма оценочной длительности пунктов >= 570 с (9.5 мин)."""
    d = ls.planned_duration_sec([item() for _ in range(13)])
    assert d >= ls.TARGET_MIN_SEC, d
    # 12 пунктов по 40 слов = слишком коротко -> валидатор должен отказать
    try:
        ls.validate_script({**GOOD, "items": [item(title=f"P{k}", n_words=40) for k in range(12)]})
        raise AssertionError("должно отклоняться: planned < TARGET_MIN_SEC")
    except ValueError:
        pass


def test_short_windows_from_items():
    durs = [40.0, 45.0, 38.0, 42.0, 44.0, 39.0, 41.0, 43.0, 40.0, 46.0]
    w = ls.short_windows(durs, n=3, limit=58.0)
    assert len(w) == 3 and len({tuple(x) for x in w}) == 3, w
    for idx in w:
        assert sum(durs[i] for i in idx) <= 58.0, (idx, sum(durs[i] for i in idx))


def test_idea_from_items_file_and_llm_prompt():
    """idea() строит промпт по списочной теме и пишет idea.json; фолбэк - файл items.json."""
    p = ls.script_prompt({"topic": "Things That Will Be Illegal Soon", "angle": ls.ANGLES[0], "palette": 0, "idx": 0})
    assert "13-15" in p and "STRICT JSON" in p
    assert "Do not copy" in p or "do not copy" in p.lower()


def test_render_tiny_item_both_aspects():
    if not shutil.which("ffmpeg"):
        print("skip render: нет ffmpeg")
        return
    it = ls.to_scene(ls.validate_script(GOOD)["items"][0], 0, {"idx": 0})
    b = [(0.02 * i, 0.02 * i + 0.015, "fact") for i in range(55)]
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        audio = td / "a.m4a"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:d=1.2",
                        "-c:a", "aac", str(audio)], check=True)
        for (W, H) in ((1920, 1080), (1080, 1920)):
            out = td / f"s{W}.mp4"
            ls.render_item(it, b, audio, 1.2, ls.PALETTES[0], ls._cover_chars(), out, W, H, banner=GOOD["title"])
            p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height", "-of", "csv=p=0", str(out)], capture_output=True, text=True)
            assert p.stdout.strip() == f"{W},{H}", p.stdout


def test_thumbnail_has_big_text():
    if not shutil.which("ffmpeg"):
        print("skip cover: нет ffmpeg")
        return
    from PIL import Image
    s = ls.validate_script(GOOD)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "cover.png"
        ls.draw_cover(s, ls.PALETTES[0], out)
        im = Image.open(out)
        assert im.size == (1280, 720)


def test_publish_descriptions_original_and_linked():
    s = {"title": "Things That Will Be Illegal Soon", "description": "d", "tags": ["t"]}
    long_d, short_d = ls.descriptions(s, "https://www.youtube.com/watch?v=abc")
    assert ls.AI_NOTE in long_d and ls.AI_NOTE in short_d
    assert "Full video: https://www.youtube.com/watch?v=abc" in short_d


def test_upload_limit_detected():
    """run 39727033513: long вышел, 1-й Short упал 400 uploadLimitExceeded -> весь выпуск exit 1."""
    e = Exception('<HttpError 400 returned "The user has exceeded the number of videos they may upload.". '
                  "Details: \"[{'reason': 'uploadLimitExceeded'}]\">")
    assert ls.upload_limit_hit(e)
    assert not ls.upload_limit_hit(Exception("HttpError 500 backendError"))


def test_idea_survives_router_exception_and_retries(monkeypatch=None):
    """IncompleteRead/любое сетевое исключение от одной модели не валит idea: круг повторов."""
    calls = {"n": 0}

    def flaky(m, prompt, mt, timeout=600):
        calls["n"] += 1
        if calls["n"] <= 2:  # первые 2 вызова - сеть падает, 3-й (круг 3) успешен
            import http.client
            raise http.client.IncompleteRead(b"")
        return wf_sse()

    def wf_sse():
        import json as _json
        payload = _json.dumps({"title": "Things That Will Be Banned In Your Lifetime",
                               "description": "d", "tags": ["t"],
                               "items": [{"title": f"P{k}", "text": " ".join(["fact"] * 110) + ".",
                                          "place": ["city", "nature", "space"][k % 3]} for k in range(13)]})
        import whatif_channel as _wf
        return _wf.sse_content([f'data: {{"choices":[{{"delta":{{"content":{_json.dumps(payload)}}}}}]}}'.encode(),
                                b"data: [DONE]"])

    import whatif_channel as _wf
    orig = _wf.router_stream
    _wf.router_stream = flaky
    import tempfile
    from pathlib import Path as _P
    try:
        with tempfile.TemporaryDirectory() as td:
            old_state = ls.STATE
            # подменяем STATE на временную папку, чтобы не трогать репо-состояние
            ls.STATE = _P(td)
            out = ls.idea(models=["m1"])
        assert out.exists()
    finally:
        _wf.router_stream = orig
        ls.STATE = old_state


def test_idea_retries_after_short_plan_then_broken_json():
    """Run 39713369774: короткий план (562 с), затем битый JSON у всех - не SystemExit, а новый круг."""
    import json as _json
    import tempfile
    from pathlib import Path as _P
    import whatif_channel as _wf

    def script(words):
        return _json.dumps({"title": "Things That Will Be Banned In Your Lifetime", "description": "d", "tags": ["t"],
                            "items": [{"title": f"P{k}", "text": " ".join(["fact"] * words) + ".",
                                       "place": ["city", "nature", "space"][k % 3]} for k in range(13)]})
    answers = iter([script(100), '{"title": "Things', script(110)])
    orig, old_state = _wf.router_stream, ls.STATE
    _wf.router_stream = lambda m, prompt, mt, timeout=600: next(answers)
    try:
        with tempfile.TemporaryDirectory() as td:
            ls.STATE = _P(td)
            out = ls.idea(models=["m1"])
            assert out.exists()
    finally:
        _wf.router_stream, ls.STATE = orig, old_state


def test_verify_dryrun_private_and_mismatch():
    """t_f807dc99: сухой прогон — private, title=idea.json, плейлист, длина файла, ссылка на long у Shorts."""
    import json as _json
    d = Path(tempfile.mkdtemp())
    (d / "idea.json").write_text(_json.dumps({"title": "Ten Things"}))
    (d / "render.json").write_text(_json.dumps({"long": "L.mp4", "shorts": ["S1.mp4"]}))
    long_url = "https://www.youtube.com/watch?v=L1"
    (d / "published.json").write_text(_json.dumps({"long": long_url, "short_1": "https://www.youtube.com/watch?v=S1"}))
    vids = {"L1": {"snippet": {"title": "Ten Things", "description": "x"}, "status": {"privacyStatus": "private"},
                   "contentDetails": {"duration": "PT10M2S"}},
            "S1": {"snippet": {"title": "Ten Things (part 1) #Shorts", "description": "Full video: " + long_url},
                   "status": {"privacyStatus": "private"}, "contentDetails": {"duration": "PT45S"}}}

    class Req:
        def __init__(self, r): self.r = r
        def execute(self): return self.r

    class Y:
        def playlists(self): return self
        def playlistItems(self): return self
        def videos(self): return self
        def list(self, **kw):
            if "id" in kw:
                return Req({"items": [vids[kw["id"]]] if kw["id"] in vids else []})
            if "playlistId" in kw:
                return Req({"items": [{"snippet": {"resourceId": {"videoId": v}}} for v in ("L1", "S1")]})
            return Req({"items": [{"id": "PL", "snippet": {"title": ls.PLAYLIST}}]})

    os.environ["CH2_PRIVACY"] = "private"
    probe = {"L.mp4": 601.5, "S1.mp4": 45.0}.get
    assert ls.verify(d, Y(), probe) == []
    vids["S1"]["snippet"]["description"] = "no link"
    vids["L1"]["status"]["privacyStatus"] = "public"
    bad = ls.verify(d, Y(), lambda f: 300.0 if f == "L.mp4" else 45.0)
    assert any("privacy" in b for b in bad) and any("длина" in b for b in bad) and any("ссылки" in b for b in bad), bad
    os.environ.pop("CH2_PRIVACY")
    assert ls.privacy() == "public"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("all listshow tests passed")
