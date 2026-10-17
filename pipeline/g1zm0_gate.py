#!/usr/bin/env python3
"""Content ID гейт G1zm0 (t_d53850f6). Шаг cron (g1zm0-gate.yml), без sleep в раннере daily-video.

daily-video с G1ZM0_GATE=1: 05_publish грузит ролик unlisted и пишет запись в .state/g1zm0_gate.json.
Каждые 30 мин этот скрипт опрашивает YouTube по записям:
  pending / моложе MIN_AGE_H -> ждём (через 24 ч один TG-алерт);
  claimed -> ролик private, перегенерация: dispatch daily-video с attempt+1 (другой эталон и промпт);
            после MAX_ATTEMPTS -> blocked + TG;
  clean   -> без одобрения владельца остаётся unlisted, владельцу один TG со ссылкой;
            одобрен (--approve VIDEO_ID) -> public + плейлист жанра.

ОГРАНИЧЕНИЕ (ревью 16.10): YouTube Data API не отдаёт обычному каналу сторонние Content ID claims.
contentDetails.licensedContent = "залито партнёром и заявлено им" (claim самого владельца CMS),
rejectionReason срабатывает только на блок. Значит "clean" здесь = "API блок/claim не видит".
Фолбэк: перед --approve владелец (или агент в браузере) смотрит Studio -> Авторские права,
ссылка studio.youtube.com/video/<id>/copyright есть в TG-сообщении.
ponytail: апгрейд — Content ID API (только для партнёров с CMS) или парсинг Studio через браузер.
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g1zm0_rotation as rot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# файл на ролик (не общий json): матрица daily-video коммитит параллельно, без rebase-конфликтов
STATE_DIR = ROOT / ".state" / "g1zm0_gate"
APPROVED_DIR = ROOT / ".state" / "g1zm0_approved"
MIN_AGE_H = 2      # Content ID проверка идёт после обработки; clean раньше 2 ч не считаем
STALE_H = 24
MAX_ATTEMPTS = 4
FINAL = ("public", "claimed", "blocked")


def load(d=STATE_DIR) -> list:
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(Path(d).glob("*.json"))]


def save(items, d=STATE_DIR) -> None:
    Path(d).mkdir(parents=True, exist_ok=True)
    for e in items:
        (Path(d) / f"{e['video_id']}.json").write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")


def record(video_id, genre, meta, d=STATE_DIR, now=None) -> dict:
    """05_publish (gated): ролик загружен unlisted -> запись для гейта."""
    r = meta.get("rotation") or {}
    now = now or dt.datetime.now(dt.timezone.utc)
    e = {"video_id": video_id, "genre": genre, "day": r.get("day") or now.date().isoformat(),
         "attempt": r.get("attempt", 0), "ref": r.get("ref"),
         "uploaded_at": now.isoformat(), "status": "pending"}
    save([e], d)
    return e


def pending_today(genre, day, d=STATE_DIR) -> bool:
    """Guard: unlisted выпуск RSS не видит -> ретрай-слот не делает дубль (genre=None: любой жанр)."""
    return any(e["day"] == day.isoformat() and genre in (None, e["genre"]) and e["status"] != "claimed"
               for e in load(d))


def owner_msg(e) -> str:
    v = e["video_id"]
    return (f"🎧 G1zm0 [{e['genre']}] {e['day']} (попытка {e['attempt'] + 1}, эталон {e['ref'] or 'нет'}): "
            f"Content ID claim через API не найден, ролик unlisted: https://youtu.be/{v}\n"
            f"Проверь Studio -> Авторские права: https://studio.youtube.com/video/{v}/copyright\n"
            f"Одобрить публикацию: gh workflow run g1zm0-gate.yml -f approve={v}")


def step(items, youtube, now, dispatch, notify, on_public, approved_dir=APPROVED_DIR) -> list:
    """Один проход по незакрытым записям. dispatch(genre, day, attempt); notify(text); on_public(vid, genre)."""
    for e in items:
        if e["status"] in FINAL:
            continue
        vid = e["video_id"]
        age_h = (now - dt.datetime.fromisoformat(e["uploaded_at"])).total_seconds() / 3600
        st = rot.yt_claim_status(youtube, vid)
        if st == "claimed":
            youtube.videos().update(part="status", body={"id": vid, "status": {
                "privacyStatus": "private", "selfDeclaredMadeForKids": False}}).execute()
            if e["attempt"] + 1 < MAX_ATTEMPTS:
                e["status"] = "claimed"
                dispatch(e["genre"], e["day"], e["attempt"] + 1)
                notify(f"⚠️ G1zm0 [{e['genre']}] {e['day']}: Content ID claim на {vid} (эталон {e['ref']}), "
                       f"ролик private, перегенерация попытка {e['attempt'] + 2}")
            else:
                e["status"] = "blocked"
                notify(f"❌ G1zm0 [{e['genre']}] {e['day']}: claim на всех {MAX_ATTEMPTS} попытках, выпуск дня пропущен")
            continue
        if st == "pending" or age_h < MIN_AGE_H:
            if age_h > STALE_H and not e.get("stale_alerted"):
                e["stale_alerted"] = True
                notify(f"⚠️ G1zm0 {vid}: статус Content ID не готов за {STALE_H} ч")
            continue
        # clean: публикация только с одобрением владельца
        if rot.publish_if_approved(youtube, vid, vid, approved_dir):
            e["status"] = "public"
            on_public(vid, e["genre"])
            notify(f"✅ G1zm0 опубликован: https://youtu.be/{vid}")
        elif not e.get("notified"):
            e["notified"] = True
            e["status"] = "await_approval"
            notify(owner_msg(e))
    return items


def main() -> int:
    from importlib import import_module

    from common import tg_send
    from watchdog import gh

    if "--approve" in sys.argv:
        vid = sys.argv[sys.argv.index("--approve") + 1].strip()
        if vid:
            rot.approve(APPROVED_DIR, vid)
            print(f"approved {vid}")
    items = load()
    if not any(e["status"] not in FINAL for e in items):
        print("gate: нет открытых записей")
        return 0
    pub = import_module("05_publish")
    yt = pub._get_youtube_service()

    def dispatch(genre, day, attempt):
        gh("actions/workflows/daily-video.yml/dispatches", {"ref": "master", "inputs": {
            "genre": genre, "g1zm0_day": day, "g1zm0_attempt": str(attempt)}})

    save(step(items, yt, dt.datetime.now(dt.timezone.utc), dispatch, tg_send,
              lambda vid, genre: pub.add_to_genre_playlist(yt, vid, genre)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
