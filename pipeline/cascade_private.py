#!/usr/bin/env python3
"""M13/M10: шортс ведёт «Full mix» на скрытый/удалённый long-form = зритель видит «видео недоступно».
Каскад: public-шортс, чей Full mix указывает на не-public ролик канала, -> private. Только private, не delete.
  python3 cascade_private.py   # env YOUTUBE_TOKEN_JSON (authorized_user JSON), stdlib only
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/youtube/v3/"
FULL_MIX = re.compile(r"Full mix:\s*https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})")


def orphans(videos: list[dict]) -> list[tuple[str, str]]:
    """videos: {id, privacy, description}. -> [(short_id, long_id)] public-шортсов на не-public/удалённый long."""
    status = {v["id"]: v["privacy"] for v in videos}
    out = []
    for v in videos:
        m = FULL_MIX.search(v.get("description") or "")
        if v["privacy"] == "public" and m and status.get(m.group(1)) != "public":
            out.append((v["id"], m.group(1)))
    return out


def empty_playlists(playlists: list[dict]) -> list[str]:
    """M18 (аудит 24.10): public-плейлист без public роликов (Chill Phonk Beats 0/2) — ссылка из описания (M15)
    ведёт зрителя в пустоту. playlists: {id, privacy, items: [privacy,...]} -> id для unlisted. Ролики не трогаем."""
    return [p["id"] for p in playlists if p["privacy"] == "public" and "public" not in p["items"]]


def channel_playlists(at) -> list[dict]:
    # ponytail: первые 50 плейлистов/50 роликов в каждом; пагинация при росте канала
    out = []
    for p in _call(at, "playlists?part=snippet,status&mine=true&maxResults=50")["items"]:
        r = _call(at, f"playlistItems?part=status&maxResults=50&playlistId={p['id']}")
        out.append({"id": p["id"], "privacy": p["status"]["privacyStatus"], "snippet": p["snippet"],
                    "items": [i.get("status", {}).get("privacyStatus") for i in r["items"]]})
    return out


def _token() -> str:
    t = json.loads(os.environ["YOUTUBE_TOKEN_JSON"])
    data = urllib.parse.urlencode({k: t[k] for k in ("client_id", "client_secret", "refresh_token")}
                                  | {"grant_type": "refresh_token"}).encode()
    return json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data, timeout=60))["access_token"]


def _call(at, path, body=None, method="GET"):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None, method=method,
                                 headers={"Authorization": "Bearer " + at, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def channel_videos(at, limit=200) -> list[dict]:
    up = _call(at, "channels?part=contentDetails&mine=true")["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page = [], ""
    while len(ids) < limit:
        r = _call(at, f"playlistItems?part=contentDetails&maxResults=50&playlistId={up}{page}")
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        if "nextPageToken" not in r:
            break
        page = "&pageToken=" + r["nextPageToken"]
    out = []
    for i in range(0, len(ids), 50):
        for v in _call(at, "videos?part=snippet,status&id=" + ",".join(ids[i:i + 50]))["items"]:
            out.append({"id": v["id"], "privacy": v["status"]["privacyStatus"], "description": v["snippet"]["description"]})
    return out


def main() -> int:
    if not os.environ.get("YOUTUBE_TOKEN_JSON"):
        print("skip: нет YOUTUBE_TOKEN_JSON")
        return 0
    at = _token()
    bad = orphans(channel_videos(at))
    for short, long_id in bad:
        _call(at, "videos?part=status", {"id": short, "status": {"privacyStatus": "private"}}, "PUT")
        print(f"private: шортс {short} вёл на недоступный long-form {long_id}")
    print(f"каскад: скрыто {len(bad)}")
    pls = channel_playlists(at)
    for pid in empty_playlists(pls):  # unlisted, не private: ссылка M15 в старых описаниях продолжает работать
        sn = next(p["snippet"] for p in pls if p["id"] == pid)
        _call(at, "playlists?part=snippet,status", {"id": pid, "snippet": {"title": sn["title"],
              "description": sn.get("description", "")}, "status": {"privacyStatus": "unlisted"}}, "PUT")
        print(f"unlisted: плейлист {pid} «{sn['title']}» без public роликов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
