#!/usr/bin/env python3
"""Сторож выпуска + отчёт об успешном выпуске (TG, по-русски).

  python3 watchdog.py           # 10:00 UTC (watchdog.yml): есть ли ролик за сегодня на канале
  python3 watchdog.py --report  # конец daily-video: ссылки на ролик и шортсы

Источник правды о выпуске — публичный RSS канала (не наш токен/лог): ролик либо виден зрителям, либо нет.
GitHub schedule опаздывает на 5-9 ч, поэтому сторож смотрит на run daily-video:
идёт/в очереди -> «ещё идёт»; сегодня не было вовсе -> сам дёргает workflow_dispatch.
"""
import datetime as dt
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET

from common import RUNS_DIR, tg_send

CHANNEL_ID = "UCoqUWdW9QaQtcbL_02YN4Gg"
RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
WORKFLOW = "daily-video.yml"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def videos_on(rss_xml: str, day: dt.date) -> list[dict]:
    """Видео из RSS с published (UTC) == day."""
    out = []
    for e in ET.fromstring(rss_xml).findall("a:entry", NS):
        pub = dt.datetime.fromisoformat(e.findtext("a:published", "", NS)).astimezone(dt.timezone.utc)
        if pub.date() == day:
            vid = e.findtext("yt:videoId", "", NS)
            out.append({"id": vid, "title": e.findtext("a:title", "", NS),
                        "url": f"https://www.youtube.com/watch?v={vid}"})
    return out


def run_date(run: dict) -> dt.date:
    return dt.datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).date()


def decide(rss_xml: str, runs: list[dict], today: dt.date) -> tuple[str | None, bool]:
    """-> (текст алерта или None если ролик есть, нужен ли workflow_dispatch). runs — новые первыми."""
    if videos_on(rss_xml, today):
        return None, False
    head = f"⚠️ {today}: на канале нет ролика за сегодня (UTC)."
    todays = [r for r in runs if run_date(r) == today]
    active = [r for r in todays if r["status"] in ("queued", "in_progress", "waiting", "pending", "requested")]
    if active:
        r = active[0]
        what = "в очереди" if r["status"] != "in_progress" else "ещё идёт"
        return f"{head} Запуск daily-video {what} (GitHub schedule опаздывает) — ждём: {r['html_url']}", False
    if todays:
        r = todays[0]
        return f"{head} Запуск daily-video сегодня завершился: {r['conclusion']}. Лог: {r['html_url']}", False
    last = f" Последний запуск: {runs[0]['conclusion']} ({runs[0]['html_url']})." if runs else ""
    return f"{head} Сегодня daily-video не запускался — запустил вручную.{last}", True


def gh(path: str, data: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    return json.loads(body) if body else {}


def fetch_rss() -> str:
    with urllib.request.urlopen(RSS_URL, timeout=30) as r:
        return r.read().decode()


def watch() -> None:
    today = dt.datetime.now(dt.timezone.utc).date()
    runs = gh(f"actions/workflows/{WORKFLOW}/runs?per_page=10")["workflow_runs"]
    alert, dispatch = decide(fetch_rss(), runs, today)
    if alert is None:
        print(f"OK: ролик за {today} есть")
        return
    if dispatch:
        gh(f"actions/workflows/{WORKFLOW}/dispatches", {"ref": os.environ.get("GITHUB_REF_NAME", "master")})
    tg_send(alert)


def report_text(run_dir, rss_videos: list[dict]) -> str:
    """Ролик из published.json (пишет 05), шортсы из shorts.json (пишет 07); нет файла — берём из RSS."""
    pub, shorts = run_dir / "published.json", run_dir / "shorts.json"
    long_url = json.loads(pub.read_text())["url"] if pub.exists() else None
    short_urls = ([f"https://youtube.com/shorts/{i}" for i in json.loads(shorts.read_text())["ids"]]
                  if shorts.exists() else [])
    if not long_url and rss_videos:
        long_url = rss_videos[0]["url"]
    if not long_url:
        return "⚠️ daily-video прошёл, но ссылку на ролик найти не удалось (нет published.json и в RSS пусто)."
    lines = [f"✅ Выпуск {dt.datetime.now(dt.timezone.utc).date()}: {long_url}"]
    lines += [f"Шортс {n}: {u}" for n, u in enumerate(short_urls, 1)] or ["Шортсы: не загружены"]
    return "\n".join(lines)


def report() -> None:
    runs = sorted(p for p in RUNS_DIR.glob("*") if p.is_dir())
    try:
        rss = videos_on(fetch_rss(), dt.datetime.now(dt.timezone.utc).date())
    except Exception as e:  # отчёт не валит выпуск
        print(f"RSS skip: {type(e).__name__}")
        rss = []
    tg_send(report_text(runs[-1], rss) if runs else "⚠️ daily-video прошёл, но runs/ пуст.")


if __name__ == "__main__":
    report() if "--report" in sys.argv else watch()
