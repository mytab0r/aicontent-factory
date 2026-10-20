#!/usr/bin/env python3
"""Сторож выпуска: логика «есть ролик сегодня» по образцу RSS + решение об алерте/dispatch.

Запуск: python3 pipeline/test_watchdog.py
"""
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchdog import already_published, days_without_long, decide, report_text, videos_on

# образец реального фида канала (сокращён)
RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>G1zm0</title>
 <published>2015-01-17T11:15:42+00:00</published>
 <entry>
  <id>yt:video:4HB26c4yow0</id>
  <yt:videoId>4HB26c4yow0</yt:videoId>
  <title>Anime Sunset Bedroom Lofi</title>
  <published>2026-10-11T19:35:53+00:00</published>
  <updated>2026-10-11T20:09:10+00:00</updated>
 </entry>
 <entry>
  <yt:videoId>late0000000</yt:videoId>
  <title>Late night</title>
  <published>2026-10-11T23:30:00-02:00</published>
 </entry>
</feed>"""
D11, D12, D13 = dt.date(2026, 10, 11), dt.date(2026, 10, 12), dt.date(2026, 10, 13)


def run(status, conclusion, day="2026-10-12", n=1):
    return {"status": status, "conclusion": conclusion, "created_at": f"{day}T09:00:00Z",
            "html_url": f"https://github.com/x/runs/{n}"}


def test_videos_on():
    assert [v["id"] for v in videos_on(RSS, D11)] == ["4HB26c4yow0"]
    # 23:30 -02:00 = 01:30 UTC следующего дня
    assert [v["id"] for v in videos_on(RSS, D12)] == ["late0000000"]
    assert videos_on(RSS, D13) == []


def test_decide():
    assert decide(RSS, [], D12) == (None, False)  # ролик есть — тишина
    # D13: роликов нет
    msg, disp = decide(RSS, [run("in_progress", None, "2026-10-13")], D13)
    assert "ещё идёт" in msg and not disp
    msg, disp = decide(RSS, [run("queued", None, "2026-10-13")], D13)
    assert "в очереди" in msg and not disp
    msg, disp = decide(RSS, [run("completed", "failure", "2026-10-13", 7)], D13)
    assert "failure" in msg and "runs/7" in msg and not disp
    msg, disp = decide(RSS, [run("completed", "success", "2026-10-12", 5)], D13)
    assert disp and "не запускался" in msg and "runs/5" in msg
    msg, disp = decide(RSS, [], D13)
    assert disp


def test_report_text():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        assert "не удалось" in report_text(d, [])
        assert "4HB26c4yow0" in report_text(d, videos_on(RSS, D11))  # фолбэк на RSS
        (d / "published.json").write_text(json.dumps({"url": "https://www.youtube.com/watch?v=abc", "id": "abc"}))
        (d / "shorts.json").write_text(json.dumps({"ids": ["s1", "s2"], "windows": []}))
        t = report_text(d, [])
        assert "watch?v=abc" in t and "shorts/s1" in t and "Шортс 2" in t


def test_already_published():
    """Дубли 12.10: schedule опоздал до 18:41 и выпустил второй long-form. Shorts не считаются."""
    rss = RSS.replace("Late night", "Late night pt.1 #Shorts")
    assert already_published(RSS, D11)
    assert not already_published(rss, D12)  # только Shorts за день
    assert not already_published(RSS, D13)




# ---- шаг 3 (t_c678b8fa): guard знает жанр — два жанра/день, ретраи не дублируют ----
RSS2 = RSS.replace(
    "<title>G1zm0</title>",
    "<title>G1zm0</title>"
    """ <entry>
  <yt:videoId>phonk000001</yt:videoId>
  <title>Neon Night Drive 🌃 Phonk Beats to Drift and Focus to</title>
  <published>2026-10-12T15:00:00+00:00</published>
  <updated>2026-10-12T15:00:00+00:00</updated>
 </entry>""",
).replace("<title>Late night</title>", "<title>Late Night Comfort 🌙 Lofi Beats to Sleep to</title>")


def test_already_published_genre():
    """Genre-aware guard: phonk-выпуск не блокируется lofi-выпуском того же дня и наоборот."""
    # 12.10: lofi + phonk оба вышли -> оба жанра заблокированы
    assert already_published(RSS2, D12, "anime lofi")
    assert already_published(RSS2, D12, "chill phonk")
    # 11.10: только lofi -> phonk свободен, lofi заблокирован
    assert already_published(RSS2, D11, "anime lofi")
    assert not already_published(RSS2, D11, "chill phonk")
    # 13.10: пусто -> оба свободны
    assert not already_published(RSS2, D13, "anime lofi")
    assert not already_published(RSS2, D13, "chill phonk")
    # legacy: без жанра — любой long-form блокирует
    assert already_published(RSS2, D11)
    assert not already_published(RSS2, D13)
    # shorts не считаются ни для какого жанра
    shorts_only = RSS.replace("Anime Sunset Bedroom Lofi", "hook #Shorts")
    assert not already_published(shorts_only, D11, "anime lofi")

def test_days_without_long():
    """P5 (18-20.10): 0 public long-form 7+ дней — канал пуст для зрителя, алерт обязан назвать срок."""
    shorts_only = RSS.replace("Anime Sunset Bedroom Lofi", "x #Shorts").replace("Late night", "y #Shorts")
    assert days_without_long(RSS, D13) == 1  # последний long-form 12.10 (UTC)
    assert days_without_long(RSS, dt.date(2026, 10, 20)) == 8
    assert days_without_long(shorts_only, D13) is None  # в ленте нет ни одного long-form
    msg, _ = decide(RSS, [], dt.date(2026, 10, 20))
    assert "8 дн" in msg, msg
    msg, _ = decide(shorts_only, [], D13)
    assert "нет ни одного" in msg, msg
    msg, _ = decide(RSS, [], D13)  # 1 день — штатно, без строки о пустом канале
    assert "дн. без" not in msg, msg


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
