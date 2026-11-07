#!/usr/bin/env python3
"""S1 ch2 breakout-finder: темы только из хитов стикмен-каналов (>=10x медианы канала).

Только read-only YouTube Data API v3: search.list / channels.list / videos.list.
Квота считается по каждому вызову (search=100, list=1) и жёстко режется бюджетом (--budget, по умолчанию 3000).
Токен: YOUTUBE_TOKEN_JSON (OAuth ch1, scope youtube.readonly) — только чтение публичной статистики.

  scan  : поиск роликов за 30 дн -> каналы (возраст, просмотры за 30 дн) -> медиана канала -> хиты -> шаблон вопроса
  check : идеи из --ideas JSON -> топ-10 поиска -> свободно / занято / мёртвая
Вывод: JSON в stdout между маркерами BREAKOUT_JSON_BEGIN/END (CI-лог; артефакты для данных не используем).
"""
import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/youtube/v3/"
COST = {"search": 100, "channels": 1, "videos": 1}  # единицы квоты YouTube Data API v3
SEED_QUERIES = ["how did ancient humans", "why it sucked to be"]
WHO = r"(humans?|people|ancient|early|medieval|prehistoric|cave ?m[ae]n|romans?|egyptians?|vikings?|women|men)"
TEMPLATES = [  # порядок = приоритет; первый совпавший побеждает
    ("Why it sucked to be X", re.compile(r"\bsucked to be\b|\bworst (jobs?|time|things?)\b", re.I)),
    ("Why we never eat X", re.compile(r"\bwhy (we|you|people|humans)\b.*\b(never|don'?t|stopped|no longer)\b.*\b(eat|eating|drink)", re.I)),
    ("What ancient humans actually did", re.compile(r"\bwhat (did )?" + WHO + r"\b.*\b(actually|really|do|did|used to)\b", re.I)),
    ("Why did humans start X", re.compile(r"\bwhy did " + WHO + r"\b.*\bstart", re.I)),
    ("How did humans X", re.compile(r"\bhow (did |the )?" + r"(\w+ )?" + WHO + r"\b", re.I)),
]


class QuotaBudget(Exception):
    pass


def median_views(views):
    """Медиана просмотров канала. Пусто -> 0."""
    v = [int(x) for x in views if x is not None]
    return float(statistics.median(v)) if v else 0.0


def multiple(views, median):
    """Кратность ролика к медиане канала; медиана 0 -> 0 (не делим на ноль, такой канал не судим)."""
    return round(views / median, 2) if median > 0 else 0.0


def breakouts(videos, k=10.0):
    """videos: [{'views':int,...}] одного канала -> (медиана, хиты >= k x медианы, по убыванию кратности)."""
    med = median_views([v["views"] for v in videos])
    hits = [dict(v, multiple=multiple(v["views"], med)) for v in videos
            if med > 0 and v["views"] >= k * med]  # порог по сырому отношению: 9.999x не округлять до 10x
    return med, sorted(hits, key=lambda h: -h["multiple"])


def template_of(title):
    for name, rx in TEMPLATES:
        if rx.search(title):
            return name
    return "other"


def occupancy(views):
    """Правила топ-10: хоть один >50k -> занято; все <100 (или пусто) -> мёртвая;
    max <1000 -> копии темы провалились (мёртвая); иначе свободно."""
    if not views or max(views) < 100:
        return "dead"
    if max(views) > 50_000:
        return "taken"
    if max(views) < 1_000:
        return "dead"  # копии темы были, но провалились
    return "free"


class YT:
    def __init__(self, token, budget):
        self.token, self.budget, self.spent = token, budget, 0

    def call(self, ep, **params):
        if ep not in COST:
            raise ValueError(f"запрещённый endpoint {ep}")  # read-only: только search/channels/videos
        if self.spent + COST[ep] > self.budget:
            raise QuotaBudget(f"{ep}: бюджет {self.budget}, потрачено {self.spent}")
        self.spent += COST[ep]
        req = urllib.request.Request(API + ep + "?" + urllib.parse.urlencode(params),
                                     headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def stats(self, ids):
        out = {}
        ids = list(dict.fromkeys(ids))
        for i in range(0, len(ids), 50):
            r = self.call("videos", part="snippet,statistics", id=",".join(ids[i:i + 50]), maxResults=50)
            for it in r.get("items", []):
                out[it["id"]] = {"id": it["id"], "title": it["snippet"]["title"],
                                 "channel_id": it["snippet"]["channelId"], "channel": it["snippet"]["channelTitle"],
                                 "published": it["snippet"]["publishedAt"],
                                 "views": int(it["statistics"].get("viewCount", 0))}
        return out


def access_token():
    t = json.loads(os.environ["YOUTUBE_TOKEN_JSON"])
    body = urllib.parse.urlencode({"client_id": t["client_id"], "client_secret": t["client_secret"],
                                   "refresh_token": t["refresh_token"], "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", body, timeout=30) as r:
        return json.load(r)["access_token"]


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def scan(yt, now, queries, pages, max_channels, k, max_age_days, min_views_30d):
    since = iso(now - dt.timedelta(days=30))
    ids = []
    for q in queries:
        tok = None
        for _ in range(pages):
            p = dict(part="id", q=q, type="video", order="viewCount", publishedAfter=since, maxResults=50,
                     relevanceLanguage="en")
            if tok:
                p["pageToken"] = tok
            r = yt.call("search", **p)
            ids += [it["id"]["videoId"] for it in r.get("items", [])]
            tok = r.get("nextPageToken")
            if not tok:
                break
    seed = yt.stats(ids)
    by_ch = {}
    for v in seed.values():
        by_ch[v["channel_id"]] = by_ch.get(v["channel_id"], 0) + v["views"]
    ch_ids = sorted(by_ch, key=lambda c: -by_ch[c])
    chans = {}
    for i in range(0, len(ch_ids), 50):
        r = yt.call("channels", part="snippet,statistics", id=",".join(ch_ids[i:i + 50]), maxResults=50)
        for it in r.get("items", []):
            pub = dt.datetime.fromisoformat(it["snippet"]["publishedAt"].replace("Z", "+00:00"))
            chans[it["id"]] = {"channel_id": it["id"], "channel": it["snippet"]["title"],
                               "created": it["snippet"]["publishedAt"], "age_days": (now - pub).days,
                               "subs": int(it["statistics"].get("subscriberCount", 0) or 0),
                               "videos_total": int(it["statistics"].get("videoCount", 0) or 0)}
    young = [c for c in ch_ids if c in chans and chans[c]["age_days"] < max_age_days]
    result, considered = [], []
    for cid in young:
        if len(considered) >= max_channels:
            break
        try:
            r = yt.call("search", part="id", channelId=cid, type="video", order="date", maxResults=50)
        except QuotaBudget:
            break
        vids = list(yt.stats([it["id"]["videoId"] for it in r.get("items", [])]).values())
        recent = [v for v in vids if v["published"] >= since]
        v30 = sum(v["views"] for v in recent)  # нижняя граница: публичный API не отдаёт просмотры канала за 30 дн
        info = dict(chans[cid], views_30d_lower_bound=v30, sample=len(vids))
        considered.append(info)
        if v30 < min_views_30d:
            continue
        med, hits = breakouts(vids, k)
        info["median_views"] = med
        for h in hits:
            result.append({"channel": info["channel"], "channel_id": cid, "channel_age_days": info["age_days"],
                           "channel_median_views": med, "video_id": h["id"], "title": h["title"],
                           "url": f"https://www.youtube.com/watch?v={h['id']}", "views": h["views"],
                           "published": h["published"], "multiple": h["multiple"],
                           "question_template": template_of(h["title"])})
    result.sort(key=lambda h: -h["multiple"])
    return {"seed_videos": len(seed), "seed_channels": len(ch_ids), "young_channels": len(young),
            "channels_checked": considered, "hits": result}


def check(yt, ideas):
    out = []
    for idea in ideas:
        try:
            r = yt.call("search", part="id", q=idea["title"], type="video", order="relevance", maxResults=10)
        except QuotaBudget:
            break
        st = yt.stats([it["id"]["videoId"] for it in r.get("items", [])])
        views = sorted((v["views"] for v in st.values()), reverse=True)
        out.append(dict(idea, top10_views=views, verdict=occupancy(views),
                        top10=[{"title": v["title"], "views": v["views"], "channel": v["channel"]}
                               for v in sorted(st.values(), key=lambda v: -v["views"])[:3]]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["scan", "check"])
    ap.add_argument("--budget", type=int, default=3000)
    ap.add_argument("--k", type=float, default=10.0)
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--max-channels", type=int, default=8)
    ap.add_argument("--max-age-days", type=int, default=365)
    ap.add_argument("--min-views-30d", type=int, default=500_000)
    ap.add_argument("--queries", default="|".join(SEED_QUERIES))
    ap.add_argument("--ideas", default="config/ch2_ideas.json")
    a = ap.parse_args(argv)
    yt = YT(access_token(), min(a.budget, 3000))
    now = dt.datetime.now(dt.timezone.utc)
    if a.mode == "scan":
        rep = scan(yt, now, a.queries.split("|"), a.pages, a.max_channels, a.k, a.max_age_days, a.min_views_30d)
        rep["params"] = {k: getattr(a, k) for k in ("k", "max_age_days", "min_views_30d", "queries", "pages")}
    else:
        rep = {"ideas": check(yt, json.load(open(a.ideas, encoding="utf-8")))}
    rep.update(mode=a.mode, generated=iso(now), quota_spent=yt.spent, quota_budget=yt.budget)
    print("BREAKOUT_JSON_BEGIN")
    print(json.dumps(rep, ensure_ascii=False))
    print("BREAKOUT_JSON_END")
    print(f"quota spent {yt.spent}/{yt.budget}", file=sys.stderr)


if __name__ == "__main__":
    main()
