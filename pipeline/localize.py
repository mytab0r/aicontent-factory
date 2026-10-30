#!/usr/bin/env python3
"""ES/pt-BR localizations (title/description) + субтитры для роликов ch1 (t_b9eb61b2).

Флаг vars.LOCALIZE: '1' включает, иначе no-op. Один путь для новых и уже опубликованных роликов:
  localize_video(youtube, video_id, cues)  -> videos.update(part=localizations) + captions.insert es/pt-BR
Источник реплик: cues.json из owning_channel.render (тайминги TTS); для старых роликов — EN ASR-трек
YouTube (captions.download). Перевод — 9router (common.router_post), $0.
  python localize.py backfill [N]   -> догнать N последних роликов «The Economics of Owning» (по умолчанию 10)
Квота: videos.update 50 + 2x captions.insert 400 + list ≈ 900 ед./ролик из 10 000/сутки.
Требует scope youtube.force-ssl (youtube_oauth.SCOPES).
"""
import io
import json
import os
import re
import sys
from pathlib import Path

LANGS = {"es": ("Spanish (neutral Latin American)", "Español"), "pt-BR": ("Brazilian Portuguese", "Português (Brasil)")}
# t_b87507e0 (30.10): glm убран — 404 (нет активных кредов на 9router). auto-cheap-combo — живой
# второй фолбэк (проверено прямым запросом к 9router).
MODELS = ["auto-worker-combo", "auto-cheap-combo"]


def enabled() -> bool:
    return os.environ.get("LOCALIZE", "0").strip() == "1"


# ---------- SRT ----------

def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(cues) -> str:
    return "".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{txt}\n\n" for i, (a, b, txt) in enumerate(cues, 1))


def _sec(ts: str) -> float:
    h, m, s = ts.replace(",", ".").split(":")
    return round(int(h) * 3600 + int(m) * 60 + float(s), 3)


def parse_srt(text: str) -> list:
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        m = next((re.match(r"(\S+) --> (\S+)", ln) for ln in lines if "-->" in ln), None)
        if m:
            body = " ".join(ln.strip() for ln in lines[lines.index(m.string) + 1:] if ln.strip())
            out.append((_sec(m.group(1)), _sec(m.group(2)), body))
    return out


def write_cues(path: Path, said: list, pad: float = 0.25) -> None:
    """said = [(text, seg_dur)] из render: сегмент = речь + pad тишины; реплика показывается без pad."""
    t, cues = 0.0, []
    for text, dur in said:
        cues.append([round(t, 3), round(t + dur - pad, 3), text])
        t += dur
    path.write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")


# ---------- перевод ----------

def check_translation(src: dict, out: dict) -> dict:
    lines = out.get("lines")
    if not (out.get("title") or "").strip() or not (out.get("description") or "").strip():
        raise ValueError("пустой title/description")
    if not isinstance(lines, list) or len(lines) != len(src["lines"]) or not all(isinstance(x, str) and x.strip() for x in lines):
        raise ValueError(f"lines: нужно {len(src['lines'])}, есть {len(lines) if isinstance(lines, list) else lines!r}")
    return {"title": out["title"].strip()[:100], "description": out["description"].strip()[:5000], "lines": lines}


def llm_translate(src: dict, lang: str) -> dict:
    from common import router_post
    prompt = (f"Translate this YouTube Shorts metadata and subtitle lines from English to {LANGS[lang][0]}. "
              "Keep numbers, $ amounts, URLs and #hashtags unchanged; natural spoken style; same number of lines, same order.\n"
              'Return STRICT JSON only: {"title": str (max 100 chars), "description": str, "lines": [str, ...]}\n\n'
              + json.dumps(src, ensure_ascii=False))
    err = None
    for model in MODELS:
        try:
            resp = router_post("/chat/completions", {"model": model, "stream": False, "max_tokens": 6000,
                                                     "response_format": {"type": "json_object"},
                                                     "messages": [{"role": "user", "content": prompt}]})
            text = resp["choices"][0]["message"]["content"]
            return check_translation(src, json.loads(re.search(r"\{.*\}", text, re.S).group(0)))
        except (RuntimeError, ValueError, KeyError, IndexError, AttributeError, TypeError) as e:
            print(f"translate {lang} {model}: {e}"[:300])
            err = e
    raise RuntimeError(f"нет перевода {lang}: {err}")


# ---------- YouTube ----------

def source_cues(youtube, video_id: str) -> list:
    """Для уже опубликованных роликов: EN-трек (ручной приоритетнее ASR)."""
    caps = [c for c in youtube.captions().list(part="snippet", videoId=video_id).execute().get("items", [])
            if c["snippet"].get("language", "").startswith("en")]
    if not caps:
        raise RuntimeError(f"{video_id}: нет EN-субтитров (ASR ещё не готов?)")
    cap = sorted(caps, key=lambda c: c["snippet"].get("trackKind") == "asr")[0]
    raw = youtube.captions().download(id=cap["id"], tfmt="srt").execute()
    return parse_srt(raw.decode("utf-8") if isinstance(raw, bytes) else raw)


def localize_video(youtube, video_id: str, cues: list, translate=llm_translate):
    if not enabled():
        return None
    from googleapiclient.http import MediaIoBaseUpload
    v = youtube.videos().list(part="snippet,localizations", id=video_id).execute()["items"][0]
    sn = v["snippet"]
    src = {"title": sn["title"], "description": sn.get("description", ""), "lines": [c[2] for c in cues]}
    have = {c["snippet"]["language"] for c in youtube.captions().list(part="snippet", videoId=video_id).execute().get("items", [])
            if c["snippet"].get("trackKind") != "asr"}
    locs = dict(v.get("localizations") or {})
    base = sn.get("defaultLanguage") or "en"
    locs.setdefault(base, {"title": sn["title"], "description": sn.get("description", "")})  # без неё update снесёт en
    done = {"localizations": [], "captions": []}
    for lang, (_, name) in LANGS.items():
        if lang in locs and lang in have:
            continue
        tr = translate(src, lang)
        locs[lang] = {"title": tr["title"], "description": tr["description"]}
        done["localizations"].append(lang)
        if lang not in have:
            srt = to_srt([(a, b, t) for (a, b, _), t in zip(cues, tr["lines"])]).encode("utf-8")
            youtube.captions().insert(part="snippet", body={"snippet": {"videoId": video_id, "language": lang, "name": name,
                                                                        "isDraft": False}},
                                      media_body=MediaIoBaseUpload(io.BytesIO(srt), mimetype="application/octet-stream")).execute()
            done["captions"].append(lang)
    if done["localizations"]:
        # videos.update(part=localizations) требует snippet.defaultLanguage — он ставится при загрузке (05_publish)
        youtube.videos().update(part="localizations", body={"id": video_id, "localizations": locs}).execute()
    print(f"localize {video_id}: {done}")
    return done


def backfill(n: int = 10) -> list:
    from owning_channel import _youtube
    y = _youtube()
    up = y.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = y.playlistItems().list(part="snippet", playlistId=up, maxResults=50).execute().get("items", [])
    ids = [i["snippet"]["resourceId"]["videoId"] for i in items if i["snippet"]["title"].startswith("The Economics of Owning")][:n]
    return [(vid, localize_video(y, vid, source_cues(y, vid))) for vid in ids]


if __name__ == "__main__":
    if sys.argv[1:2] == ["backfill"]:
        if not enabled():
            sys.exit("LOCALIZE!=1: no-op")
        print(backfill(int(sys.argv[2]) if len(sys.argv) > 2 else 10))
    else:
        sys.exit(__doc__)
