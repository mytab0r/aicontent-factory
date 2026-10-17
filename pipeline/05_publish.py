#!/usr/bin/env python3
"""Шаг 5: загрузить video.mp4 последнего run на YouTube (resumable upload).

Запускать интерпретатором с google-api-python-client:
  /opt/hermes/.venv/bin/python pipeline/05_publish.py

Требует валидный токен youtube_oauth.py --check (scope youtube.upload).
Помечает видео как synthetic content (containsSyntheticMedia) — см.
AGENTS.md п.4. selfDeclaredMadeForKids=False (канал не детский).
"""
import json
import re
import sys
from pathlib import Path

from common import latest_run_dir
from youtube_oauth import TOKEN_PATH, check_auth


def _get_youtube_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    from google_auth_httplib2 import AuthorizedHttp

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    return build("youtube", "v3", http=AuthorizedHttp(creds, http=upload_http()))


def upload_http(timeout=300):
    """build_http(), не голый httplib2.Http: он убирает 308 из redirect_codes — без этого
    resumable upload падает RedirectMissingLocation (14.10). timeout 300 с вместо 60:
    чанк 4 МБ на медленном аплинке ПК ловил read timeout на 65%."""
    from googleapiclient.http import build_http
    http = build_http()
    http.timeout = timeout
    return http


def upload_resumable(request, max_errors=8, sleep=None):
    """Resumable upload, переживающий обрывы: после сетевой ошибки следующий next_chunk
    шлёт status-запрос (Content-Range */size) и продолжает с принятого байта, а не с нуля."""
    import time
    sleep = sleep or time.sleep
    response, errors = None, 0
    while response is None:
        try:
            status, response = request.next_chunk(num_retries=5)
        except (TimeoutError, ConnectionError, OSError) as e:
            errors += 1
            if errors > max_errors:
                raise
            print(f"upload: {type(e).__name__}, resume {errors}/{max_errors}")
            request._in_error_state = True  # googleapiclient: следующий вызов = запрос статуса
            sleep(min(60, 5 * errors))
            continue
        if status:
            print(f"upload {int(status.progress() * 100)}%")
    return response


def is_upload_limit(e) -> bool:
    """YouTube 400 uploadLimitExceeded: дневной лимит загрузок канала (общий для daily-video и A/B)."""
    from googleapiclient.errors import HttpError
    return isinstance(e, HttpError) and b"uploadLimitExceeded" in (e.content or b"")


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


def full_description(text: str, chapters=None) -> str:
    """Аудит 4HB26c4yow0: хэштеги + AI-disclosure; треклист-главы (>=3, с 0:00) для часового микса."""
    extra = [s for s in (AI_NOTE, HASHTAGS) if s not in text]
    if chapters and len(chapters) >= 3:
        extra.insert(0, "Tracklist:\n" + "\n".join(chapters))
    return "\n\n".join([text.rstrip(), *extra])


def title_with_length(title: str, duration_sec) -> str:
    """Ресёрч 14.10: лидеры ниши пишут длину в заголовке (Lofi Girl 1:04 ч 811k, Chill Crossing «1 Hour» 150k).
    Метка только по фактической длине (>=55 мин), без фейковых чисел; уже есть «Hour» — не трогаем."""
    if not duration_sec or duration_sec < 3300 or re.search(r"\bhours?\b", title, re.I):
        return title[:100]
    h = max(1, int(duration_sec // 3600))
    tag = f" | {h} Hour" + ("s" if h > 1 else "")
    return title[:100 - len(tag)].rstrip() + tag


def publish(run_dir: Path) -> str:
    from googleapiclient.http import MediaFileUpload

    idea = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))
    video_path = run_dir / "video.mp4"
    if not video_path.exists():
        raise SystemExit(f"нет video.mp4 в {run_dir} — сначала 04_assemble.py")

    meta_path = run_dir / "music_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    chaps = meta.get("chapters")
    youtube = _get_youtube_service()
    body = {
        "snippet": {
            "title": title_with_length(idea["title"], meta.get("duration")),
            "description": full_description(idea["description"], chaps),
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

    try:
        response = upload_resumable(request)
    except Exception as e:
        if not is_upload_limit(e):
            raise
        from common import tg_send
        # транзиентно: выпуск не валим, video.mp4 остаётся в runs/, published.json не пишем (07 shorts пропустит)
        # ponytail: перезалив в следующий слот не автоматизирован (вне скоупа t_24f3f36c); добавить при повторах
        tg_send(f"⏸ YouTube uploadLimitExceeded: дневной лимит загрузок исчерпан, слот пропущен. Видео осталось в {video_path}")
        print(f"skip: uploadLimitExceeded, {video_path} оставлен для следующего слота")
        return None

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
