#!/usr/bin/env python3
"""Гейт Content ID (t_d53850f6): готовый трек нельзя публиковать сразу.

Сценарий:
  1. upload_unlisted()  — заливает video как unlisted (05_publish.py, но privacy=unlisted).
  2. wait_verdict()     — раз в N минут videos.list по себе: claim виден как
     contentDetails.licensedContent=true (наша копия трека совпала с референсом
     правообладателя в Content ID) и/или status.rejectionReason=claim/copyright.
  3. clean = True       -> 05_publish.py переключает видео в public.
     clean = False       -> видео удаляется, возврат claim -> перегенерация
     с другим эталоном/промптом (pipeline/refpool.pick(+1)).

Примечание: детальный отчёт по claim-ам живёт только в YouTube Studio
(Content ID API закрыт для обычных каналов), но видео с активным
аудиозаявлением помечается licensedContent=true, и это ровно тот сигнал,
который нужен гейту: монетизация ушла правообладателю = публиковать нельзя.
"""
import datetime as dt
import json
import os
import time
from pathlib import Path

# Content ID матч обычно всплывает за минуты; потолок — слот релиза (180 мин job timeout,
# upload часа ~35 мин уже потрачен).
CHECK_INTERVAL_SEC = int(os.environ.get("CLAIM_CHECK_INTERVAL_SEC") or 300)
CLAIM_TIMEOUT_SEC = int(os.environ.get("CLAIM_TIMEOUT_SEC") or 5400)


def _youtube():
    from youtube_oauth import TOKEN_PATH, check_auth
    assert check_auth(quiet=True), "нет валидного OAuth-токена YouTube"
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.http import build_http
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    http = build_http()
    http.timeout = 300
    return build("youtube", "v3", http=AuthorizedHttp(creds, http=http))


def upload_unlisted(run_dir: Path) -> str:
    """Загрузка video.mp4 как unlisted через 05_publish.build_body (весь билд
    метаданных тот же, меняется только privacyStatus). Возвращает videoId."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pub", Path(__file__).parent / "05_publish.py")
    pub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pub)

    from googleapiclient.http import MediaFileUpload
    video_path = Path(run_dir) / "video.mp4"
    assert video_path.is_file(), f"нет video.mp4 в {run_dir}"
    youtube = _youtube()
    idea = json.loads((Path(run_dir) / "idea.json").read_text(encoding="utf-8"))
    meta_path = Path(run_dir) / "music_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    body = pub.build_body(idea, meta)
    body["status"]["privacyStatus"] = "unlisted"
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True,
                            chunksize=1024 * 1024 * 4)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = pub.upload_resumable(request)
    vid = response["id"]
    (Path(run_dir) / "uploaded_unlisted.json").write_text(
        json.dumps({"id": vid, "ts": dt.datetime.now(dt.timezone.utc).isoformat()}), encoding="utf-8")
    return vid


def fetch_status(youtube, video_id: str) -> dict:
    r = youtube.videos().list(part="status,contentDetails", id=video_id).execute()
    items = r.get("items", [])
    if not items:
        return {"exists": False}
    it = items[0]
    return {
        "exists": True,
        "uploadStatus": it.get("status", {}).get("uploadStatus"),
        "rejectionReason": it.get("status", {}).get("rejectionReason"),
        "privacyStatus": it.get("status", {}).get("privacyStatus"),
        "licensedContent": bool(it.get("contentDetails", {}).get("licensedContent")),
    }


def has_claim(st: dict) -> str | None:
    """None = чисто, строка = причина. Активный Content ID матч на собственном
    видео -> licensedContent=true; rejected claim/copyright -> rejectionReason."""
    if not st.get("exists"):
        return "video-not-found"
    if st.get("rejectionReason") in ("claim", "copyright"):
        return "rejected:" + st["rejectionReason"]
    if st.get("licensedContent"):
        return "licensedContent"
    return None


def wait_verdict(video_id: str, sleep=time.sleep, deadline_sec=None, log=print,
                 youtube=None, fetch=None) -> bool:
    """True = чисто (можно публиковать), False = заявка. Поллинг status/contentDetails.
    youtube/fetch прокидываются для тестов (без OAuth)."""
    youtube = youtube or _youtube()
    fetch = fetch or fetch_status
    deadline_sec = CLAIM_TIMEOUT_SEC if deadline_sec is None else deadline_sec
    end = time.time() + deadline_sec
    while True:
        st = fetch(youtube, video_id)
        claim = has_claim(st)
        if claim:
            log(f"claim: {claim} ({st})")
            return False
        if time.time() > end:
            log(f"claim: чисто за {(deadline_sec or CLAIM_TIMEOUT_SEC) // 60} мин ({st})")
            return True
        sleep(CHECK_INTERVAL_SEC)


def make_public(youtube, video_id: str) -> None:
    youtube.videos().update(part="status",
                            body={"id": video_id, "status": {"privacyStatus": "public"}}).execute()


def delete_video(youtube, video_id: str) -> None:
    youtube.videos().delete(id=video_id).execute()


def main() -> None:
    """standalone: ждать вердикт по unlisted-загрузке последнего run и публиковать/удалять."""
    from common import latest_run_dir
    run_dir = latest_run_dir()
    up = json.loads((run_dir / "uploaded_unlisted.json").read_text(encoding="utf-8"))
    youtube = _youtube()
    if wait_verdict(up["id"]):
        make_public(youtube, up["id"])
        (run_dir / "published.json").write_text(
            json.dumps({"url": "https://www.youtube.com/watch?v=" + up["id"], "id": up["id"]}),
            encoding="utf-8")
        print("OK: опубликовано (claim-гейт пройден)")
    else:
        delete_video(youtube, up["id"])
        print("FAIL: заявка правообладателя, видео удалено — нужна перегенерация")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
