#!/usr/bin/env python3
"""breakout_finder: медиана/кратность/хиты/занятость — чистые функции (t_2918b2ce)."""
import importlib.util
from pathlib import Path

_p = Path(__file__).resolve().parent.parent / "scripts" / "breakout_finder.py"
_s = importlib.util.spec_from_file_location("breakout_finder", _p)
bf = importlib.util.module_from_spec(_s)
_s.loader.exec_module(bf)


def test_median_and_multiple():
    assert bf.median_views([100, 300, 200]) == 200
    assert bf.median_views([100, 200, 300, 400]) == 250
    assert bf.median_views([]) == 0
    assert bf.multiple(5000, 250) == 20.0
    assert bf.multiple(5000, 0) == 0.0


def test_breakouts_threshold_and_order():
    vids = [{"id": str(i), "views": v} for i, v in enumerate([1000] * 9 + [9999, 50_000, 10_000])]
    med, hits = bf.breakouts(vids, 10)
    assert med == 1000
    assert [h["id"] for h in hits] == ["10", "11"]  # 9999 = 9.999x — не хит; 10_000 = ровно 10x — хит
    assert hits[0]["multiple"] == 50.0
    assert bf.breakouts([{"id": "a", "views": 0}] * 3)[1] == []


def test_templates():
    assert bf.template_of("How Did Ancient Humans Survive Winter?") == "How did humans X"
    assert bf.template_of("Why We Never Eat Swan Anymore") == "Why we never eat X"
    assert bf.template_of("Why It Sucked To Be A Medieval Peasant") == "Why it sucked to be X"
    assert bf.template_of("What Ancient Humans Actually Did At Night") == "What ancient humans actually did"
    assert bf.template_of("Top 10 cats") == "other"


def test_occupancy():
    assert bf.occupancy([60_000, 10]) == "taken"
    assert bf.occupancy([99, 50]) == "dead"
    assert bf.occupancy([]) == "dead"
    assert bf.occupancy([800, 300]) == "dead"  # копии темы провалились
    assert bf.occupancy([50_000, 2000]) == "free"


def test_quota_guard_and_readonly():
    yt = bf.YT("x", 150)
    yt.spent = 100
    try:
        yt.call("search", q="a")
        raise AssertionError("бюджет не сработал")
    except bf.QuotaBudget:
        pass
    try:
        yt.call("playlistItems")
        raise AssertionError("endpoint вне allowlist")
    except ValueError:
        pass
    assert set(bf.COST) == {"search", "channels", "videos"}


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
