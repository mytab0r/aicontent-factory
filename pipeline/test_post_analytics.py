#!/usr/bin/env python3
"""Пост-аналитика через 48 ч: медиана канала, флаг «разбор», выбор видео по окну. Без сети.

Запуск: python3 pipeline/test_post_analytics.py
"""
import datetime as dt
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
pa = importlib.import_module("08_post_analytics")

NOW = dt.datetime(2026, 10, 17, 12, 0, tzinfo=dt.timezone.utc)
REAL = {"collect": pa.collect}  # сетевые заглушки ниже патчат модуль — возвращаем оригиналы


def v(vid, hours_ago, ret, ctr, title="Anime Lofi"):
    return {"id": vid, "title": title, "published": NOW - dt.timedelta(hours=hours_ago),
            "retention": ret, "ctr": ctr}


def test_median():
    assert pa.median([3, 1, 2]) == 2
    assert pa.median([4, 1, 3, 2]) == 2.5
    assert pa.median([None, 5, None]) == 5
    assert pa.median([]) is None and pa.median([None]) is None


def test_due_window_48_72h():
    vids = [v("a", 47.9, 1, 1), v("b", 48, 1, 1), v("c", 71.9, 1, 1), v("d", 72, 1, 1)]
    assert [x["id"] for x in pa.due(vids, NOW)] == ["b", "c"]


def test_window_h_dispatch_override():
    assert pa.window_h("") == pa.WINDOW_H and pa.window_h(None) == pa.WINDOW_H
    assert pa.window_h("0,72") == (0, 72)
    vids = [v("a", 10, 1, 1), v("b", 50, 1, 1)]
    assert [x["id"] for x in pa.due(vids, NOW, (0, 72))] == ["a", "b"]
    for bad in ("72,0", "-1,5"):
        try:
            pa.window_h(bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def test_flag_below_median_any_metric():
    vids = [v("a", 50, 40, 5), v("b", 100, 30, 4), v("c", 200, 50, 6), v("d", 300, 35, 3)]
    rows = pa.analyse(vids, NOW)
    assert [r["id"] for r in rows] == ["a"]
    a = rows[0]
    assert a["med_retention"] == 37.5 and a["med_ctr"] == 4.5
    assert a["flags"] == [] and not a["razbor"]          # 40>37.5, 5>4.5
    vids[0] = v("a", 50, 33, 5)                            # 33 < медианы 34
    a = pa.analyse(vids, NOW)[0]
    assert a["razbor"] and a["flags"] == ["удержание"]
    vids[0] = v("a", 50, 33, 1)
    assert pa.analyse(vids, NOW)[0]["flags"] == ["удержание", "CTR"]


def test_equal_to_median_not_flagged_and_ctr_missing():
    vids = [v("a", 50, 2, None), v("b", 100, 1, None), v("c", 100, 3, None)]
    a = pa.analyse(vids, NOW)[0]
    assert a["med_retention"] == 2 and not a["razbor"]     # не ниже = без флага
    assert a["med_ctr"] is None and a["flags"] == []       # нет CTR -> не флагуем по нему


def test_shorts_compared_with_shorts():
    vids = [v("s", 50, 60, 2, "hook #Shorts"), v("s2", 100, 80, 1, "x #shorts"),
            v("s3", 100, 90, 1, "y #Shorts"), v("L", 100, 10, 9), v("L2", 100, 12, 9)]
    s = pa.analyse(vids, NOW)[0]
    assert s["med_retention"] == 80 and s["flags"] == ["удержание"]
    assert s["med_ctr"] == 1                                # 2 > 1 -> CTR ок


def test_report_text():
    vids = [v("a", 50, 30, 2), v("b", 100, 40, 4)]
    txt = pa.report_text(pa.analyse(vids, NOW), ctr_note=None)
    assert "youtu.be/a" in txt and "РАЗБОР" in txt and "30.0%" in txt and "медиана 35.0%" in txt
    assert "CTR н/д" in pa.report_text(pa.analyse(vids, NOW), ctr_note="CTR н/д: отчёт недоступен")


# ---------- reach-отчёт (YouTube Reporting API, решение владельца 17.10) ----------

REACH_CSV = (
    "time,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
    "2026-10-15,chn,vidA,1000,0.05\n"
    "2026-10-16,chn,vidA,1200,0.07\n"
    "2026-10-16,chn,vidB,500,0.02\n"
)


def test_parse_reach_csv_latest_day_wins():
    got = pa.parse_reach_csv(REACH_CSV)
    assert got["vidA"] == (1200.0, 0.07)   # строка последнего дня, не сумма/первая
    assert got["vidB"] == (500.0, 0.02)
    assert len(got) == 2


def test_empty_window_sends_nothing():
    sent = []
    pa.access_token, pa.collect = (lambda: "t"), (lambda at: ([], None))
    pa.tg_send = sent.append
    assert pa.main() == 0
    assert sent == []                        # пустое окно = молчим (решение 17.10)


def test_reach_failure_keeps_retention_report():
    sent = []
    # main() берёт реальное время: возраст роликов считаем от него, не от NOW (тест-бомба 18.10: "a" выпал из окна 48-72 ч)
    shift = dt.datetime.now(dt.timezone.utc) - NOW
    vids = [dict(x, published=x["published"] + shift) for x in (v("a", 50, 40, None), v("b", 100, 30, None), v("c", 200, 50, None))]
    pa.collect = REAL["collect"]           # предыдущий тест подменял collect — вернуть
    pa.access_token = lambda: "t"
    pa.uploads = lambda at: [dict(x) for x in vids]
    pa.metric = lambda at, ids, start, name: {"a": 40.0, "b": 30.0, "c": 50.0}
    pa.ensure_reach_job = lambda at: (_ for _ in ()).throw(RuntimeError("reach down"))
    pa.tg_send = lambda t: sent.append(t) or True
    assert pa.main() == 0
    txt = sent[-1]
    assert "удержание 40.0%" in txt          # сбой reach не валит удержание
    assert "CTR н/д" in txt
    assert "reach down" not in txt and "RuntimeError" not in txt  # сырая ошибка не в TG


def test_undelivered_report_exits_nonzero():
    pa.tg_send = lambda t: False             # TG так и не принял отчёт после повторов
    assert pa.main() == 1                    # job красный, отчёт не теряется молча


def test_tg_send_retries_then_fails():
    import os
    import time
    import urllib.request
    import common
    calls, fail_first = [], [99]

    def fake_urlopen(*a, **k):
        calls.append(1)
        if len(calls) <= fail_first[0]:
            raise ConnectionResetError("RemoteDisconnected")

    saved = (urllib.request.urlopen, time.sleep)
    os.environ.update(TG_BOT_TOKEN="x", TG_CHAT_ID="1")
    urllib.request.urlopen, time.sleep = fake_urlopen, (lambda s: None)
    try:
        assert common.tg_send("hi") is False and len(calls) == 3   # 3 попытки, потом False
        calls.clear(); fail_first[0] = 1
        assert common.tg_send("hi") is True and len(calls) == 2    # сбой, затем успех
    finally:
        urllib.request.urlopen, time.sleep = saved
        for k in ("TG_BOT_TOKEN", "TG_CHAT_ID"):
            os.environ.pop(k, None)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
