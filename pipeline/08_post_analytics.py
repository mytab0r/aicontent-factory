#!/usr/bin/env python3
"""Шаг 8: пост-аналитика через 48 ч после публикации (t_3017f17a, спец t_b4006a6e п.6).

Раз в сутки (post-analytics.yml): видео, опубликованные 48–72 ч назад (каждое попадает в окно
ровно один раз), получают удержание (averageViewPercentage) и CTR показов
(videoThumbnailImpressionsClickRate) из YouTube Analytics API. Медиана канала считается по
последним загрузкам того же типа (shorts с shorts, long-form с long-form). Ниже медианы по любой
метрике = флаг «разбор». Итог одним сообщением в TG-топик отчётов (common.tg_send).

  YOUTUBE_TOKEN_JSON=... python3 08_post_analytics.py           # отчёт
  YOUTUBE_TOKEN_JSON=... python3 08_post_analytics.py --probe   # только проверка scope вызовом API

Только stdlib: токен обновляется через oauth2.googleapis.com/token.
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from common import tg_send

WINDOW_H = (48, 72)
HISTORY = 50  # ponytail: медиана по последним 50 загрузкам (1 страница API); больше — пагинация
YT = "https://www.googleapis.com/youtube/v3/"
YTA = "https://youtubeanalytics.googleapis.com/v2/reports?"


# ---------- чистая логика (тест: test_post_analytics.py) ----------
def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def is_short(v) -> bool:
    return "#shorts" in v["title"].lower()


def due(videos, now):
    lo, hi = (now - dt.timedelta(hours=h) for h in reversed(WINDOW_H))
    return [v for v in videos if lo < v["published"] <= hi]


def analyse(videos, now):
    rows = []
    for v in due(videos, now):
        peers = [p for p in videos if is_short(p) == is_short(v)]
        med = {k: median(p[k] for p in peers) for k in ("retention", "ctr")}
        flags = [name for k, name in (("retention", "удержание"), ("ctr", "CTR"))
                 if v[k] is not None and med[k] is not None and v[k] < med[k]]
        rows.append({**v, "med_retention": med["retention"], "med_ctr": med["ctr"],
                     "flags": flags, "razbor": bool(flags)})
    return rows


def _fmt(x):
    return "н/д" if x is None else f"{x:.1f}%"


def report_text(rows, ctr_note) -> str:
    lines = ["📊 G1zm0: пост-аналитика 48 ч"]
    if not rows:
        lines.append("За окно 48–72 ч нет видео.")
    for r in rows:
        mark = "🔴 РАЗБОР (" + ", ".join(r["flags"]) + ")" if r["razbor"] else "🟢 ок"
        kind = "short" if is_short(r) else "long"
        lines.append(f"\n{mark} [{kind}] {r['title']}\nhttps://youtu.be/{r['id']}\n"
                     f"удержание {_fmt(r['retention'])} (медиана {_fmt(r['med_retention'])}), "
                     f"CTR {_fmt(r['ctr'])} (медиана {_fmt(r['med_ctr'])})")
    if ctr_note:
        lines.append(f"\n⚠️ {ctr_note}")
    return "\n".join(lines)


# ---------- сеть ----------
def access_token() -> str:
    t = json.loads(os.environ["YOUTUBE_TOKEN_JSON"])
    body = urllib.parse.urlencode({"client_id": t["client_id"], "client_secret": t["client_secret"],
                                   "refresh_token": t["refresh_token"],
                                   "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", body, timeout=30) as r:
        return json.load(r)["access_token"]


def api(url, at):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {at}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _http_err(e: urllib.error.HTTPError) -> str:
    try:
        return f"{e.code} {json.load(e)['error']['message']}"[:300]
    except Exception:
        return str(e.code)


def uploads(at):
    ch = api(YT + "channels?part=contentDetails&mine=true", at)["items"][0]
    pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    items = api(YT + f"playlistItems?part=contentDetails,snippet&maxResults={HISTORY}&playlistId={pl}", at)["items"]
    return [{"id": i["contentDetails"]["videoId"], "title": i["snippet"]["title"],
             "published": dt.datetime.fromisoformat(i["contentDetails"]["videoPublishedAt"].replace("Z", "+00:00"))}
            for i in items if i["contentDetails"].get("videoPublishedAt")]


def metric(at, ids, start, name) -> dict:
    q = urllib.parse.urlencode({"ids": "channel==MINE", "startDate": start, "endDate": dt.date.today().isoformat(),
                                "metrics": name, "dimensions": "video", "filters": "video==" + ",".join(ids),
                                "maxResults": HISTORY})
    return {r[0]: float(r[1]) for r in api(YTA + q, at).get("rows") or []}


def collect(at):
    vids = uploads(at)
    if not vids:
        return [], None
    ids, start = [v["id"] for v in vids], min(v["published"] for v in vids).date().isoformat()
    ret = metric(at, ids, start, "averageViewPercentage")  # без удержания отчёт бессмыслен: падаем
    ctr_note = None
    try:
        ctr = metric(at, ids, start, "videoThumbnailImpressionsClickRate")
    except urllib.error.HTTPError as e:  # CTR — не core-метрика, API может её не отдать
        ctr, ctr_note = {}, f"CTR н/д: {_http_err(e)}"
    for v in vids:
        v["retention"], v["ctr"] = ret.get(v["id"]), ctr.get(v["id"])
    return vids, ctr_note


def probe() -> int:
    """Проверка scope реальным вызовом: Analytics API отвечает на запрос-сводку канала.

    CTR показов (videoThumbnailImpressionsClickRate) Analytics API v2 НЕ поддерживает
    (проверено вызовом в CI run 39073550413: 400 The query is not supported; метрика есть
    только в bulk-отчётах YouTube Reporting API, требующих scope yt-analytics.readonly,
    которого у токена нет). Поэтому зонд — только по поддерживаемым метрикам."""
    at = access_token()
    q = urllib.parse.urlencode({"ids": "channel==MINE", "startDate": "2026-10-01",
                                "endDate": dt.date.today().isoformat(),
                                "metrics": "views,averageViewPercentage"})
    try:
        print("PROBE OK:", api(YTA + q, at).get("rows"))
        return 0
    except urllib.error.HTTPError as e:
        print("PROBE FAIL:", _http_err(e))
        return 1


def main() -> int:
    if "--probe" in sys.argv:
        return probe()
    try:
        vids, ctr_note = collect(access_token())
    except urllib.error.HTTPError as e:
        tg_send(f"⚠️ G1zm0 пост-аналитика 48 ч не собрана: YouTube API {_http_err(e)}")
        raise
    rows = analyse(vids, dt.datetime.now(dt.timezone.utc))
    tg_send(report_text(rows, ctr_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
