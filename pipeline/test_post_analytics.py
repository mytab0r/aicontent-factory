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
    assert "нет видео" in pa.report_text([], ctr_note=None)
    assert "CTR н/д" in pa.report_text([], ctr_note="CTR н/д: 400")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
