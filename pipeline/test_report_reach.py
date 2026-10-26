#!/usr/bin/env python3
"""28-дневный отчёт: показы обложки и CTR по видео из reach-CSV (Reporting API). Без сети.

Запуск: python3 pipeline/test_report_reach.py
"""
import importlib
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("youtube_oauth", types.SimpleNamespace(TOKEN_PATH=None, check_auth=None))
pa = importlib.import_module("08_post_analytics")
rep = importlib.import_module("06_report")

H = "date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"


def test_aggregate_sums_impressions_weighted_ctr_and_window():
    d1 = H + "20261001,c,old,999,0.9\n"                       # до окна — не считать
    d2 = H + "20261010,c,A,100,0.10\n20261010,c,B,50,0.02\n"
    d3 = H + "20261011,c,A,300,0.02\n"
    got = pa.aggregate_reach([d1, d2, d3, H], "2026-10-05")    # пустой CSV (день без данных) не ломает
    assert set(got) == {"A", "B"}
    imp, ctr = got["A"]
    assert imp == 400 and abs(ctr - (10 + 6) / 400) < 1e-9   # CTR по кликам, не среднее дней (0.06)
    assert got["B"] == (50.0, 0.02)


def test_zero_impressions_ctr_none():
    assert pa.aggregate_reach([H + "20261010,c,Z,0,0\n"], "20261001") == {"Z": (0.0, None)}


def test_latest_per_day_prefers_backfill():
    reps = [{"startTime": "d1", "createTime": "1", "id": "a"}, {"startTime": "d1", "createTime": "2", "id": "b"},
            {"startTime": "d0", "createTime": "1", "id": "c"}]
    assert [r["id"] for r in pa.latest_per_day(reps)] == ["c", "b"]


def test_report_columns_and_missing():
    h, rows = rep.add_reach_columns(["video", "views"], [["A", 5], ["Q", 1]], {"A": (400.0, 0.04)})
    assert h == ["video", "views", "thumbnailImpressions28d", "thumbnailCTR28d"]
    assert rows == [["A", 5, 400, 0.04], ["Q", 1, "н/д", "н/д"]]


def test_reach_failure_degrades_to_note():
    pa.ensure_reach_job = lambda at: (_ for _ in ()).throw(RuntimeError("403 disabled"))
    reach, note = rep.reach_28d("t")
    assert reach == {} and "н/д" in note and "403" not in note
    pa.ensure_reach_job, pa.reach_window = (lambda at: "j"), (lambda at, j, days: {})
    assert "ещё не сформирован" in rep.reach_28d("t")[1]       # пустой первый запуск — не ошибка
    pa.reach_window = lambda at, j, days: {"A": (1.0, 0.5)} if days == 28 else None
    assert rep.reach_28d("t") == ({"A": (1.0, 0.5)}, None)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
