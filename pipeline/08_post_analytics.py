#!/usr/bin/env python3
"""Шаг 8: пост-аналитика через 48 ч после публикации (t_3017f17a, спец t_b4006a6e п.6).

Раз в сутки (post-analytics.yml): видео, опубликованные 48–72 ч назад (каждое попадает в окно
ровно один раз), получают удержание (averageViewPercentage, Analytics API) и CTR показов
(Reporting API, bulk-отчёт channel_reach_basic_a1: video_thumbnail_impressions_ctr; Analytics API
v2 CTR не отдаёт — 400, проверено CI 39073550413). Медиана канала считается по
последним загрузкам того же типа (shorts с shorts, long-form с long-form). Ниже медианы по любой
метрике = флаг «разбор». Пустое окно = молчание. Итог одним сообщением в TG-топик отчётов (common.tg_send).

  YOUTUBE_TOKEN_JSON=... python3 08_post_analytics.py           # отчёт
  YOUTUBE_TOKEN_JSON=... python3 08_post_analytics.py --probe   # только проверка scope вызовом API

Только stdlib: токен обновляется через oauth2.googleapis.com/token.
"""
import csv
import datetime as dt
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from time import sleep as time_sleep

from common import tg_send

WINDOW_H = (48, 72)
HISTORY = 50  # ponytail: медиана по последним 50 загрузкам (1 страница API); больше — пагинация
YT = "https://www.googleapis.com/youtube/v3/"
YTA = "https://youtubeanalytics.googleapis.com/v2/reports?"
REPTR = "https://youtubereporting.googleapis.com/v1/"
REACH_TYPE = "channel_reach_basic_a1"  # bulk-отчёт «Охват»: показы превью + CTR


# ---------- чистая логика (тест: test_post_analytics.py) ----------
def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def is_short(v) -> bool:
    return "#shorts" in v["title"].lower()


def window_h(raw):
    """'lo,hi' из workflow_dispatch input; пусто (cron) = WINDOW_H."""
    if not raw or not raw.strip():
        return WINDOW_H
    lo, hi = (float(x) for x in raw.split(","))
    if not 0 <= lo < hi:
        raise ValueError(f"window_h: нужно 0 <= lo < hi, получено {raw!r}")
    return lo, hi


def due(videos, now, window=WINDOW_H):
    lo, hi = (now - dt.timedelta(hours=h) for h in reversed(window))
    return [v for v in videos if lo < v["published"] <= hi]


def analyse(videos, now, window=WINDOW_H):
    rows = []
    for v in due(videos, now, window):
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
def with_retry(fn, tries=3, pause=20):
    """P17: сетевой сбой (URLError/5xx/таймаут) -> повтор; 4xx (нет scope/токен) — сразу наружу."""
    for i in range(1, tries + 1):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == tries:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if i == tries:
                raise
        time_sleep(pause * i)


def access_token() -> str:
    return with_retry(_token_raw)


def _token_raw() -> str:
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


def parse_reach_csv(text) -> dict:
    """CSV reach-отчёта -> {video_id: (impressions, ctr)}; на видео берём строку последнего дня.

    ponytail: impressions не суммируем по дням (CTR суточный) — для флага «ниже медианы»
    достаточно среза последнего дня; upgrade — пересчёт CTR из сумм показов/кликов."""
    rows = csv.reader(io.StringIO(text))
    header = next(rows, [])
    idx = {name: i for i, name in enumerate(header)}
    ivid, iv, ic = idx["video_id"], idx["video_thumbnail_impressions"], idx["video_thumbnail_impressions_ctr"]
    it = idx.get("time", idx.get("date", 0))
    out = {}
    for r in rows:
        if len(r) <= max(ivid, iv, ic, it) or not r[ivid]:
            continue
        cur = out.get(r[ivid])
        if cur is None or r[it] > cur[1]:
            out[r[ivid]] = ((float(r[iv]), float(r[ic])), r[it])
    return {vid: val for vid, (val, _) in out.items()}


def ensure_reach_job(at) -> str:
    """Идемпотентно: существующий job channel_reach_basic_a1 или создание (однократно)."""
    for j in api(REPTR + "jobs", at).get("jobs") or []:
        if j.get("reportTypeId") == REACH_TYPE:
            return j["jobId"]
    req = urllib.request.Request(REPTR + "jobs", json.dumps({"reportTypeId": REACH_TYPE,
                                                             "name": "post-analytics-reach"}).encode(),
                                 headers={"Authorization": f"Bearer {at}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["jobId"]


def reach_ctr(at, job_id) -> dict:
    """Последний CSV джоба за 7 дней -> {video_id: (impressions, ctr)}. Пусто = ещё не выгружен."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
    reps = api(REPTR + f"jobs/{job_id}/reports?" + urllib.parse.urlencode({"createdAfter": cutoff}), at).get("reports") or []
    if not reps:
        return {}
    latest = max(reps, key=lambda r: r["startTime"])
    req = urllib.request.Request(latest["downloadUrl"], headers={"Authorization": f"Bearer {at}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return parse_reach_csv(r.read().decode("utf-8", "replace"))


def collect(at):
    vids = uploads(at)
    if not vids:
        return vids, None
    ids, start = [v["id"] for v in vids], min(v["published"] for v in vids).date().isoformat()
    ret = metric(at, ids, start, "averageViewPercentage")  # без удержания отчёт бессмыслен: падаем
    ctr, ctr_note = {}, None
    try:
        ctr = reach_ctr(at, ensure_reach_job(at))  # сбой reach не валит удержание (решение 17.10)
        if not ctr:
            ctr_note = "CTR н/д: reach-отчёт YouTube ещё не сформирован (суточная выгрузка, задержка до 2 дней)"
    except Exception as e:  # noqa: BLE001 — любая ошибка reach = одна русская строка, без сырого текста
        print("reach unavailable:", type(e).__name__, e, file=sys.stderr)
        ctr_note = "CTR н/д: нет доступа к reach-отчёту до перевыпуска токена YouTube"
    for v in vids:
        v["retention"], v["ctr"] = ret.get(v["id"]), ctr.get(v["id"])
    return vids, ctr_note


def granted_scopes(at) -> str:
    req = urllib.request.Request("https://oauth2.googleapis.com/tokeninfo?access_token=" + urllib.parse.quote(at))
    with urllib.request.urlopen(req, timeout=30) as r:
        # ' . ' вместо точек: URL scope не секрет, но GH-маскер режет его как подстроку секрета
        return json.load(r).get("scope", "?").replace(".", " ").replace(" googleapis com/auth/", " -> ")


def probe() -> int:
    """Проверка scope реальными вызовами: Analytics API — гейт, Reporting API — статус.

    Факт (CI 39078811056): у токена scope youtube, youtube.readonly, youtube.upload —
    yt-analytics.readonly НЕТ. Analytics v2 работает и с youtube.readonly (PROBE analytics
    зелёный в каждом прогоне), а Reporting API требует строго yt-analytics.readonly -> 403.
    До перевыпуска токена CTR в отчёте = «н/д» (мягкая деградация в collect()); чинится
    только новым consent-токеном с yt-analytics.readonly — вне рамок этой карточки."""
    try:
        at = with_retry(_token_raw)
    except Exception as e:  # noqa: BLE001 — P17: сбой без алерта = слепой цикл улучшений
        print("PROBE FAIL (token):", type(e).__name__, e)
        tg_send("⚠️ G1zm0: пост-аналитика не собралась (нет токена/сети) — чиню, детали в логе CI")
        return 1
    q = urllib.parse.urlencode({"ids": "channel==MINE", "startDate": "2026-10-01",
                                "endDate": dt.date.today().isoformat(),
                                "metrics": "views,averageViewPercentage"})
    try:
        print("PROBE granted scopes:", granted_scopes(at))
        print("PROBE analytics:", with_retry(lambda: api(YTA + q, at)).get("rows"))
    except Exception as e:  # noqa: BLE001
        print("PROBE FAIL (analytics):", _http_err(e) if isinstance(e, urllib.error.HTTPError) else repr(e))
        tg_send("⚠️ G1zm0: пост-аналитика не собралась (YouTube Analytics недоступен) — чиню, детали в логе CI")
        return 1
    try:
        print("PROBE reporting jobs:", [j.get("reportTypeId") for j in api(REPTR + "jobs", at).get("jobs") or []])
    except urllib.error.HTTPError as e:
        print("PROBE reporting: недоступен —", _http_err(e), "(нужен scope yt-analytics read only; CTR = н/д)")
    return 0


def main() -> int:
    if "--probe" in sys.argv:
        return probe()
    try:
        vids, ctr_note = collect(access_token())
    except urllib.error.HTTPError as e:
        print("collect fail:", _http_err(e), file=sys.stderr)  # сырая ошибка — в лог CI, не владельцу
        tg_send("⚠️ G1zm0: пост-аналитика 48 ч не собралась — чиню, детали в логе CI")
        raise
    rows = analyse(vids, dt.datetime.now(dt.timezone.utc), window_h(os.environ.get("WINDOW_H")))
    if not rows:
        return 0  # пустое окно 48–72 ч = молчим (решение владельца 17.10)
    if not tg_send(report_text(rows, ctr_note)):
        print("report NOT delivered to TG", file=sys.stderr)
        return 1  # недоставленный отчёт = красный job, а не молчаливая потеря
    return 0


if __name__ == "__main__":
    sys.exit(main())
