#!/usr/bin/env python3
"""Шаг 5: загрузить video.mp4 последнего run на YouTube (resumable upload).

Запускать интерпретатором с google-api-python-client:
  /opt/hermes/.venv/bin/python pipeline/05_publish.py

Требует валидный токен youtube_oauth.py --check (scope youtube.upload).
Помечает видео как synthetic content (containsSyntheticMedia) — см.
AGENTS.md п.4. selfDeclaredMadeForKids=False (канал не детский).
"""
import json
import sys
from pathlib import Path

from common import latest_run_dir
from youtube_oauth import TOKEN_PATH, check_auth


def _get_youtube_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    return build("youtube", "v3", credentials=creds)


def publish(run_dir: Path) -> str:
    from googleapiclient.http import MediaFileUpload

    idea = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))
    video_path = run_dir / "video.mp4"
    if not video_path.exists():
        raise SystemExit(f"нет video.mp4 в {run_dir} — сначала 04_assemble.py")

    youtube = _get_youtube_service()
    body = {
        "snippet": {
            "title": idea["title"][:100],
            "description": idea["description"],
            "tags": idea.get("tags", []),
            "categoryId": "10",  # Music
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    # YouTube API v3 (на момент реализации) помечает синтетический контент
    # через containsSyntheticMedia в status — если поле недоступно на этом
    # аккаунте/API-версии, запрос всё равно пройдёт без него (visual-пометка
    # в самом видео уже вшита в 04_assemble.py, см. docs/DECISIONS.md).
    body["status"]["containsSyntheticMedia"] = True

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True, chunksize=1024 * 1024 * 4)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"upload {int(status.progress() * 100)}%")

    video_id = response["id"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"OK: опубликовано {url}")
    return url


def main() -> None:
    if not check_auth(quiet=True):
        print("ERROR: нет валидного OAuth-токена. Сначала youtube_oauth.py --check/--auth-url.")
        sys.exit(1)
    run_dir = latest_run_dir()
    publish(run_dir)


if __name__ == "__main__":
    main()
