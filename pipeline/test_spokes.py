#!/usr/bin/env python3
"""Self-check hub-and-spoke (t_705386b0): один idea.json -> Short/Pinterest/X/блог/TG с меткой источника.
Запуск: python3 pipeline/test_spokes.py (без сети)."""
import json
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spokes as sp

IDEA = {
    "title": "What the Tower Card Really Means in Love",
    "hook": "Pulled the Tower in a love reading? It's not the end you think.",
    "beats": [
        {"say": "The Tower is the most feared card in the deck.", "big": "XVI", "label": "the tower"},
        {"say": "In love it rarely means a breakup; it means a truth comes out.", "big": "78%", "label": "readers misread it"},
        {"say": "Upright, it clears what was built on illusion.", "big": "UP", "label": "sudden clarity"},
        {"say": "Reversed, the shake-up is internal and slower.", "big": "REV", "label": "inner shift"},
        {"say": "Ask what you've been avoiding, not who will leave.", "big": "?", "label": "the real question"},
    ],
    "description": "The Tower card in love readings, upright and reversed. For entertainment only.",
    "tags": ["tarot", "tower card", "tarot love reading"],
}


def test_deeplink_per_platform():
    seen = set()
    for p in sp.PLATFORMS:
        u = sp.funnel_url("tarot", p)
        q = parse_qs(urlparse(u).query)
        assert u.startswith("https://t.me/Tar0_Astral_bot?start="), u
        start = q["start"][0]
        # Telegram: start-параметр 1-64 символа [A-Za-z0-9_-]
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", start), start
        assert sp.source_platform(start) == p
        seen.add(start)
    assert len(seen) == len(sp.PLATFORMS), "метка источника должна различать площадки"
    # совместимость с уже розданными ссылками t_255c099a (yt_tarot / yt_manifest / yt_love)
    assert sp.funnel_url("tarot", "yt").endswith("start=yt_tarot")


def test_utm_for_non_bot_channel():
    u = sp.funnel_url("owning", "pin")
    q = parse_qs(urlparse(u).query)
    assert "t.me" not in u, "канал 1 без таро-воронки (решение t_018254ae)"
    assert q["utm_source"] == ["pinterest"] and q["utm_campaign"] == ["owning"], q


def test_source_platform_unknown():
    assert sp.source_platform("direct") == "other" and sp.source_platform("gh_awesome") == "other"


def test_by_platform_and_kill_rule():
    # (users.src, старты, плательщики) за окно 14 дней — как отдаёт SOURCE_SQL бота
    rows = [("yt_tarot", 300, 6), ("yt_love", 100, 2), ("pin_tarot", 60, 3), ("x_tarot", 3, 0),
            ("tg_tarot", 40, 4), ("gh_awesome", 7, 0), ("direct", 0, 0)]
    agg = sp.by_platform(rows)
    assert agg["yt"] == {"starts": 400, "payers": 8, "cr_pct": 2.0, "share_pct": 78.4}, agg["yt"]
    assert agg["other"]["starts"] == 7 and agg["blog"]["starts"] == 0
    # KILL: вклад <1% в переходы за 14 дней -> площадку отключить (x = 3/510 = 0.59%, blog = 0)
    assert sp.kill_list(agg) == ["blog", "x"]
    assert sp.kill_list(sp.by_platform([])) == [], "без трафика решения нет (нет знаменателя)"
    assert "src" in sp.SOURCE_SQL and "payment" in sp.SOURCE_SQL


def test_stats_csv_append():
    import csv
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "stats_sources.csv"
        rows = [("yt_tarot", 10, 1), ("x_tarot", 0, 0)]
        sp.append_stats(out, rows, "2026-10-19")
        sp.append_stats(out, rows, "2026-10-20")
        got = list(csv.DictReader(out.open()))
    assert len(got) == 2 * (len(sp.PLATFORMS) + 1), "строка на площадку в день, заголовок один раз"
    yt = next(r for r in got if r["platform"] == "yt")
    assert yt == {"date": "2026-10-19", "window_days": "14", "platform": "yt", "starts": "10", "payers": "1",
                  "cr_pct": "10.0", "share_pct": "100.0", "kill": "0"}, yt
    assert next(r for r in got if r["platform"] == "x")["kill"] == "1"


def test_pin_origin_ends_in_pin_deeplink():
    """Пин -> лендинг статьи -> бот: переход с Pinterest должен прийти в бота как start=pin_<ниша>,
    иначе строка pin в stats_sources = 0 навсегда и KILL убьёт Pinterest на первом трафике (ревью run 1014)."""
    s = sp.build_spokes(IDEA, "tarot", slug="tower-card-love")
    link = urlparse(s["pinterest"]["link"])
    landing = s["pinterest"]["landing_markdown"]
    permalink = re.search(r"^permalink: (\S+)$", landing, re.M).group(1)
    assert link.path.endswith(permalink), (link.path, permalink)  # ссылка пина = страница лендинга
    starts = re.findall(r"start=([A-Za-z0-9_-]+)", landing)
    assert starts == ["pin_tarot"] and sp.source_platform(starts[0]) == "pin", starts
    assert "start=pin_" not in s["blog"]["markdown"], "основная статья остаётся blog_*"
    assert re.search(r"^sitemap: false$", landing, re.M) and "canonical_url:" in landing, "дубль вне индекса"
    agg = sp.by_platform([(starts[0], 50, 2), ("yt_tarot", 50, 1)])
    assert agg["pin"]["starts"] == 50 and "pin" not in sp.kill_list(agg)
    # канал без бота: лендинг ведёт UTM pinterest
    o = sp.build_spokes(dict(IDEA, hook="h"), "owning", "s")["pinterest"]["landing_markdown"]
    assert "utm_source=pinterest" in o and "t.me" not in o


def test_no_hook_no_duplicate():
    idea = {k: v for k, v in IDEA.items() if k != "hook"}
    s = sp.build_spokes(idea, "tarot", "x")
    first = IDEA["beats"][0]["say"]
    assert s["pinterest"]["description"].count(first) == 1, s["pinterest"]["description"]
    assert sum(first in t for t in s["x"]["thread"]) == 1
    assert s["tg"]["text"].count(first) == 1


def test_cta_matches_channel():
    owning = {"title": "Why Renting Beats Owning", "hook": "A car costs $1,100 a month.", "tags": ["finance"],
              "beats": [{"say": "Insurance is $250.", "big": "$250", "label": "insurance"}] * 3}
    s = sp.build_spokes(owning, "owning", "x")
    blob = json.dumps(s, ensure_ascii=False).lower()
    assert "tarot" not in blob, "канал 1 (финансы) не должен звать в таро-бота"
    assert "entertainment" not in blob
    assert "tarot" in json.dumps(sp.build_spokes(IDEA, "tarot", "x")).lower()


def test_spokes_text_limits_and_cta():
    s = sp.build_spokes(IDEA, "tarot", slug="tower-card-love")
    # каждая площадка получает СВОЮ метку источника
    assert "start=yt_tarot" in s["short"]["pinned_comment"]
    assert "start=tg_tarot" in s["tg"]["text"] and len(s["tg"]["text"]) <= 1024
    assert all(len(t) <= 280 for t in s["x"]["thread"]) and len(s["x"]["thread"]) >= 3
    assert "start=x_tarot" in s["x"]["thread"][-1], "ссылка только в последнем твите (CTA в конце треда)"
    assert not any("http" in t for t in s["x"]["thread"][:-1])
    pin = s["pinterest"]
    assert len(pin["title"]) <= 100 and len(pin["description"]) <= 500
    # пин ведёт на статью блога (не на t.me: Pinterest режет редиректы/мессенджеры), метка pinterest
    assert "utm_source=pinterest" in pin["link"] and pin["link"].startswith(sp.BLOG_BASE)
    blog = s["blog"]["markdown"]
    assert blog.startswith("---\n") and "title:" in blog and "description:" in blog
    assert "start=blog_tarot" in blog and "for entertainment" in blog.lower()
    meta = re.search(r'^description: "(.*)"$', blog, re.M).group(1)
    assert 50 <= len(meta) <= 160, len(meta)
    for b in IDEA["beats"]:
        assert b["say"] in blog


def test_spokes_vary_with_content():
    other = dict(IDEA, title="Mercury Retrograde: 3 Things to Avoid", hook="Mercury goes retrograde next week.")
    a, b = sp.build_spokes(IDEA, "tarot", "a"), sp.build_spokes(other, "tarot", "b")
    for k in ("tg", "pinterest"):
        assert json.dumps(a[k]) != json.dumps(b[k]), k


def test_pin_image_size():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "pin.png"
        sp.pin_image(IDEA, p)
        from PIL import Image
        assert Image.open(p).size == (1000, 1500)


def test_write_all():
    with tempfile.TemporaryDirectory() as td:
        run = Path(td)
        (run / "idea.json").write_text(json.dumps(dict(IDEA, channel="tarot")), encoding="utf-8")
        out = sp.write_all(run)
        for f in ("spokes.json", "pin.png", "x.txt", "tg.txt", "blog.md", "blog_pin.md"):
            assert (out / f).exists() and (out / f).stat().st_size > 0, f


if __name__ == "__main__":
    test_deeplink_per_platform()
    test_utm_for_non_bot_channel()
    test_source_platform_unknown()
    test_by_platform_and_kill_rule()
    test_stats_csv_append()
    test_cta_matches_channel()
    test_pin_origin_ends_in_pin_deeplink()
    test_no_hook_no_duplicate()
    test_spokes_text_limits_and_cta()
    test_spokes_vary_with_content()
    test_pin_image_size()
    test_write_all()
    print("all spokes tests passed")
