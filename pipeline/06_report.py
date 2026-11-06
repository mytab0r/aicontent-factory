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
import importlib
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


def add_reach_columns(headers, rows, reach):
    """Дописать к строкам (первый столбец = video id) показы обложки и CTR за 28 дней; нет данных = н/д."""
    out = []
    for row in rows:
        imp, ctr = reach.get(row[0], (None, None))
        out.append(list(row) + ["н/д" if imp is None else int(imp),
                                "н/д" if ctr is None else round(ctr, 4)])
    return headers + ["thumbnailImpressions28d", "thumbnailCTR28d"], out


def reach_28d(access_token):
    """Показы/CTR обложек из Reporting API (channel_reach_basic_a1): Analytics v2 эти метрики
    не отдаёт (400 query not supported). Сбой reach не валит отчёт — столбцы н/д + русская пометка."""
    pa = importlib.import_module("08_post_analytics")
    try:
        reach = pa.reach_window(access_token, pa.ensure_reach_job(access_token), days=28)
    except Exception as e:  # noqa: BLE001 — сырая ошибка в лог, в отчёт одна строка
        print("reach unavailable:", type(e).__name__, e, file=sys.stderr)
        return {}, "Показы/CTR н/д: отчёт «Охват» YouTube недоступен (см. лог)."
    if not reach:
        return {}, "Показы/CTR н/д: отчёт «Охват» ещё не сформирован (первые данные через 24–48 ч после создания job)."
    return reach, None


def build_report() -> str:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    from google.auth.transport.requests import Request

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    if not creds.valid:
        creds.refresh(Request())  # creds.token нужен для Reporting API (stdlib-запросы в 08)
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
    reach, note = reach_28d(creds.token)
    headers, rows = add_reach_columns(headers, rows, reach)

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
    if note:
        lines += ["", note]

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
