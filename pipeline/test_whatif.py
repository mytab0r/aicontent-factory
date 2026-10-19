#!/usr/bin/env python3
"""Self-check режима code-2D «What if...» (S1 ch2): флаг, скрипт-DSL, синхрон по словам, Shorts-окна, рендер.
Запуск: python3 pipeline/test_whatif.py (без сети; рендер-тест нужен ffmpeg + pillow)."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import whatif_channel as wf

WORDS = "one two three four five six seven eight nine ten eleven twelve".split()


def scene(n_words=60, **kw):
    s = {"place": "city", "text": " ".join(["word"] * n_words) + ".",
         "cast": [{"id": "you", "x": 0.4, "mood": "happy"}],
         "actions": [{"word": 2, "do": "jump", "who": "you"}, {"word": 5, "do": "spawn", "prop": "heart", "x": 0.7, "y": 0.4}]}
    s.update(kw)
    return s


GOOD = {"title": "What if you never felt fear?", "description": "A thought experiment.", "tags": ["what if"],
        "characters": [{"id": "you", "color": "#ffb000", "label": "You"}],
        "scenes": [scene() for _ in range(11)]}


def test_flag_on_off():
    os.environ.pop("CODE2D", None)
    assert not wf.enabled()
    for v, want in (("1", True), ("0", False), ("", False), ("true", True)):
        os.environ["CODE2D"] = v
        assert wf.enabled() is want, v
    os.environ.pop("CODE2D")
    # выключенный флаг: main = no-op с exit 0, ничего не рендерит и не публикует
    r = subprocess.run([sys.executable, str(Path(wf.__file__)), "render"], capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if k != "CODE2D"})
    assert r.returncode == 0 and "disabled" in r.stdout, (r.returncode, r.stdout, r.stderr)


def test_validate_script_normalizes_dsl():
    s = wf.validate_script({**GOOD, "scenes": [scene(actions=[
        {"word": 999, "do": "jump", "who": "you"},           # индекс за пределом -> зажат
        {"word": 1, "do": "rm -rf", "who": "you"},            # неизвестное действие -> выброшено
        {"word": 3, "do": "spawn", "prop": "unicorn"},        # неизвестный реквизит -> нормализован
        {"word": 4, "do": "walk", "who": "ghost", "x": 5}],   # чужой персонаж -> выброшено
        place="mars")] + [scene() for _ in range(10)]})
    a = s["scenes"][0]["actions"]
    assert [x["do"] for x in a] == ["spawn", "jump"], a  # отсортированы по слову
    assert a[1]["word"] == 59 and a[0]["prop"] in wf.PROPS
    assert s["scenes"][0]["place"] in wf.PLACES


def test_validate_rejects_short_or_wrong_title():
    for bad in ({**GOOD, "scenes": GOOD["scenes"][:3]}, {**GOOD, "title": "Fear explained"}):
        try:
            wf.validate_script(bad)
            raise AssertionError("должно отклоняться")
        except ValueError:
            pass


def test_rotation_varies_topic_and_palette():
    with tempfile.TemporaryDirectory() as td:
        picks = [wf.next_plan(Path(td)) for _ in range(len(wf.TOPICS))]
    assert len({p["topic"] for p in picks}) == len(wf.TOPICS)
    for a, b in zip(picks, picks[1:]):
        assert a["palette"] != b["palette"] and a["angle"] != b["angle"]


def test_word_times_map_actions_to_tts_boundaries():
    b = [(0.1 * i, 0.1 * i + 0.08, w) for i, w in enumerate(WORDS)]
    assert wf.word_time(b, 3, len(WORDS)) == b[3][0]  # равные счёты -> точное слово
    assert wf.word_time(b, 6, 6) == b[-1][0] or wf.word_time(b, 6, 6) >= b[6][0]  # иначе пропорция
    assert wf.word_time(b, 0, 24) == 0.0 and wf.word_time(b, 12, 24) == b[6][0]


def test_state_sync_jump_happens_at_word():
    sc = wf.validate_script(GOOD)["scenes"][0]
    b = [(0.3 * i, 0.3 * i + 0.25, "word") for i in range(60)]
    tl = wf.timeline(sc, b)
    t_jump = b[2][0]
    before, mid = wf.char_state(tl, "you", t_jump - 0.05), wf.char_state(tl, "you", t_jump + 0.3)
    assert before["dy"] == 0 and mid["dy"] < 0, (before, mid)
    assert not wf.props_at(tl, b[5][0] - 0.05) and wf.props_at(tl, b[5][0] + 0.5)
    # караоке-субтитр подсвечивает слово, звучащее в момент t
    words, cur = wf.caption_at(b, b[7][0] + 0.01)
    assert len(words) <= 6 and cur == 7 % 6, (words, cur)
    # окно субтитра не склеивает фразы: новая фраза (заглавная) открывает новое окно
    b2 = [(i, i + .5, w) for i, w in enumerate("an email. The neighbor is arguing".split())]
    assert wf.caption_at(b2, 3.1) == (["The", "neighbor", "is", "arguing"], 1)
    assert wf.caption_at(b2, 0.1) == (["an", "email."], 0)


def test_short_windows_fit_and_differ():
    durs = [22.0, 25.0, 18.0, 30.0, 21.0, 24.0, 19.0, 26.0, 23.0, 20.0, 27.0]
    w = wf.short_windows(durs, n=3, limit=58.0)
    assert len(w) == 3 and len({tuple(x) for x in w}) == 3
    for idx in w:
        assert sum(durs[i] for i in idx) <= 58.0 and idx == list(range(idx[0], idx[-1] + 1))


def test_sse_content_joins_deltas_skips_reasoning():
    lines = [b'data: {"choices":[{"delta":{"reasoning_content":"hmm"}}]}', b"",
             b'data: {"choices":[{"delta":{"content":"{\\"a\\""}}]}', b'data: {"choices":[{"delta":{"content":": 1}"}}]}',
             b'data: {"choices":[{"finish_reason":"stop","delta":{"content":""}}]}', b"data: [DONE]"]
    assert wf.parse_json(wf.sse_content(lines)) == {"a": 1}


def test_auto_actions_fallback_is_word_synced():
    text = "You wake up at night. Your phone buzzes with money news, and fear grips you. Why now?"
    a = wf.auto_actions(text, [{"id": "you"}])
    toks = text.split()
    props = {x["prop"]: toks[x["word"]] for x in a if x["do"] == "spawn"}
    assert props.get("phone") == "phone" and props.get("coin") == "money", props
    assert any(x["do"] == "mood" and x["mood"] == "scared" for x in a)
    assert any(x["do"] in ("jump", "walk", "shake") for x in a)
    # нормализатор принимает фолбэк без потерь
    s = wf.validate_script({**GOOD, "scenes": [scene(text=text * 6, actions=wf.auto_actions(text * 6, [{"id": "you"}]))] + GOOD["scenes"][1:]})
    assert len(s["scenes"][0]["actions"]) >= 4


def test_owning_guard_counts_only_owning_titles():
    import datetime as dt
    import owning_channel as oc
    items = [("2026-10-19T01:00:00Z", "The Economics of Owning a Laundromat"),
             ("2026-10-19T02:00:00Z", "What if you never felt fear?"),
             ("2026-10-19T02:01:00Z", "What if you never felt fear? #Shorts")]
    assert oc.count_owning_today(items, dt.date(2026, 10, 19)) == 1


def test_render_tiny_scene_both_aspects():
    if not shutil.which("ffmpeg"):
        print("skip render: нет ffmpeg")
        return
    sc = wf.validate_script(GOOD)["scenes"][0]
    b = [(0.02 * i, 0.02 * i + 0.015, "word") for i in range(60)]
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        audio = td / "a.m4a"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:d=1.2",
                        "-c:a", "aac", str(audio)], check=True)
        for (W, H) in ((1920, 1080), (1080, 1920)):
            out = td / f"s{W}.mp4"
            wf.render_scene(sc, b, audio, 1.2, wf.PALETTES[0], GOOD["characters"], out, W, H, banner="What if?")
            p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height", "-of", "csv=p=0", str(out)], capture_output=True, text=True)
            assert p.stdout.strip() == f"{W},{H}", p.stdout


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("all whatif tests passed")
