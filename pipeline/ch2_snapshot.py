#!/usr/bin/env python3
"""Снапшот ch2 (@OwningItMath): по каждому ролику показы, CTR, удержание, источник трафика.

  YT_CH1_TOKEN_JSON=... python3 ch2_snapshot.py            # снапшот в stdout + reports/ch2_snapshot/
  YT_CH1_TOKEN_JSON=... python3 ch2_snapshot.py --probe    # только scope-проба

Переиспользует collect() из 08_post_analytics (тот же канал @OwningItMath, плейлист ch2 на нём же).
Только stdlib. Трафик-источник: Analytics v2 dimensions=insightTrafficSourceType (yt-analytics.readonly
не нужен — работает с youtube.readonly, проверено probe() 08-го).
"""
import datetime as dt
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("pa", os.path.join(os.path.dirname(os.path.abspath(__file__)), "08_post_analytics.py"))
pa = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(pa)

CH2_PLAYLIST_HINTS = ("Fascinating Lists", "What If")


def token_raw() -> str:
    t = json.loads(os.environ["YT_CH1_TOKEN_JSON"])
    import urllib.request
    body = urllib.parse.urlencode({"client_id": t["client_id"], "client_secret": t["client_secret"],
                                   "refresh_token": t["refresh_token"], "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", body, timeout=30) as r:
        return json.load(r)["access_token"]


def traffic_sources(at, vid, start) -> dict:
    q = urllib.parse.urlencode({"ids": "channel==MINE", "startDate": start,
                                "endDate": dt.date.today().isoformat(),
                                "metrics": "views", "dimensions": "insightTrafficSourceType",
                                "filters": f"video=={vid}", "sort": "-views"})
    rows = pa.api(pa.YTA + q, at).get("rows") or []
    return {r[0]: int(r[1]) for r in rows}


def snapshot(at) -> str:
    vids, ctr_note = pa.collect(at)
    if not vids:
        return "канал пуст: снапшотить нечего"
    lines = [f"# ch2 снапшот {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M}Z ({len(vids)} роликов)", ""]
    for v in vids:
        start = v["published"].date().isoformat()
        ts = traffic_sources(at, v["id"], start)
        top_ts = ", ".join(f"{k}={n}" for k, n in sorted(ts.items(), key=lambda x: -x[1])[:4])
        imp, ctr = (v["ctr"] or (None, None)) if v["ctr"] else (None, None)
        ret = v["retention"]
        lines.append(
            f"- {v['title']} ({v['id']}, {start}): показы={imp if imp is not None else 'н/д'}, "
            f"CTR={f'{ctr:.1f}%' if ctr is not None else 'н/д'}, "
            f"удержание={f'{ret:.1f}%' if ret is not None else 'н/д'}; трафик: {top_ts or 'нет данных'}")
    if ctr_note:
        lines.append(f"\nПримечание: {ctr_note}")
    lines.append("\nИсточник: YouTube Analytics API v2 + Reporting API (reach bulk), канал @OwningItMath.")
    return "\n".join(lines) + "\n"


def main() -> None:
    at = pa.with_retry(token_raw)
    try:
        print("SCOPES:", pa.granted_scopes(at))
    except Exception as e:  # noqa: BLE001
        print("scopes skip:", type(e).__name__)
    if "--probe" in sys.argv:
        return
    out = snapshot(at)
    d = ROOT / "reports" / "ch2_snapshot"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{dt.date.today().isoformat()}.md"
    f.write_text(out, encoding="utf-8")
    print(out)
    print(f"saved -> {f}")


if __name__ == "__main__":
    main()
