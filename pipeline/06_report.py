#!/usr/bin/env python3
"""Шаг 6: раз в N дней тянуть статистику видео через YouTube Analytics API,
писать краткий отчёт в docs/REPORTS/.

Запускать: /opt/hermes/.venv/bin/python pipeline/06_report.py
Требует валидный токен (scope youtube.readonly).

YAGNI: без Telegram-рассылки здесь — это отдельная задача оркестрации
(AGENTS.md п.1), отчёт как markdown-файл достаточен для MVP
(docs/PLAN.md "Критерии готовности").
"""
import datetime
import sys
from pathlib import Path

from common import ROOT
from youtube_oauth import TOKEN_PATH, check_auth

REPORTS_DIR = ROOT / "docs" / "REPORTS"


def _get_channel_id(youtube) -> str:
    resp = youtube.channels().list(part="id", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise SystemExit("ERROR: у авторизованного аккаунта нет YouTube-канала")
    return items[0]["id"]


def build_report() -> str:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    youtube = build("youtube", "v3", credentials=creds)
    analytics = build("youtubeAnalytics", "v2", credentials=creds)

    channel_id = _get_channel_id(youtube)
    today = datetime.date.today()
    start = today - datetime.timedelta(days=28)

    resp = analytics.reports().query(
        ids=f"channel=={channel_id}",
        startDate=start.isoformat(),
        endDate=today.isoformat(),
        metrics="views,estimatedMinutesWatched,subscribersGained,likes",
        dimensions="video",
        sort="-views",
        maxResults=25,
    ).execute()

    rows = resp.get("rows", [])
    headers = [h["name"] for h in resp.get("columnHeaders", [])]

    lines = [
        f"# Отчёт {today.isoformat()} (последние 28 дней)",
        "",
        f"Канал: {channel_id}",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    if not rows:
        lines.append("(нет данных за период — возможно, ещё не было загрузок)")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not check_auth(quiet=True):
        print("ERROR: нет валидного OAuth-токена. Сначала youtube_oauth.py --check/--auth-url.")
        sys.exit(1)

    report = build_report()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"{datetime.date.today().isoformat()}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"report -> {out_path}")
    print(report)


if __name__ == "__main__":
    main()
