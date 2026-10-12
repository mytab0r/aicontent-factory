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


def playlist_title(genre: str) -> str:
    return f"{genre.title()} Beats"


def add_to_genre_playlist(youtube, video_id: str, genre: str) -> str:
    """One playlist per genre: reuse by title, create on first use (public)."""
    title = playlist_title(genre)
    # ponytail: first page (50) only; paginate when channel has >50 playlists
    items = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute().get("items", [])
    pid = next((i["id"] for i in items if i["snippet"]["title"] == title), None)
    if pid is None:
        pid = youtube.playlists().insert(part="snippet,status", body={
            "snippet": {"title": title, "description": f"{genre} - instrumental, AI-generated"},
            "status": {"privacyStatus": "public"},
        }).execute()["id"]
    youtube.playlistItems().insert(part="snippet", body={"snippet": {
        "playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
    return pid


HASHTAGS = "#lofi #animelofi #studymusic"
AI_NOTE = "AI-generated music and visuals (synthetic content)."


def full_description(text: str) -> str:
    """Аудит 4HB26c4yow0: хэштеги + AI-disclosure в описании (идемпотентно)."""
    extra = [s for s in (AI_NOTE, HASHTAGS) if s not in text]
    return "\n\n".join([text.rstrip(), *extra])


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
            "description": full_description(idea["description"]),
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
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
    # 07_shorts берёт отсюда ссылку на long-form
    (run_dir / "published.json").write_text(json.dumps({"url": url, "id": video_id}), encoding="utf-8")
    cover = run_dir / "cover.png"
    if cover.exists():
        try:  # кастомная обложка требует верифицированный канал — не валим выпуск
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(cover), mimetype="image/png")).execute()
        except Exception as e:
            print(f"thumbnail skip: {type(e).__name__}: {e}")
    meta = run_dir / "music_meta.json"
    if meta.exists():
        genre = json.loads(meta.read_text(encoding="utf-8"))["genre"]
        print(f"playlist -> {add_to_genre_playlist(youtube, video_id, genre)} ({genre})")
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
