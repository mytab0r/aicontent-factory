#!/usr/bin/env python3
"""S1 ch1 «Economics of Owning» (@OwningItMath, UC82JHx5Cl_kuxND-qHHwzTg): нарративные Shorts.

CHANNEL=owning: 01_idea.py пишет EN-скрипт через 9router (next_plan + idea_prompt + validate_script),
этот модуль озвучивает его (edge-tts, бесплатно) и собирает 1080x1920 инфографику (PIL + ffmpeg):
  python owning_channel.py render   -> runs/<last>/video.mp4
  python owning_channel.py guard    -> exit 0 если сегодня ещё < MAX_PER_DAY загрузок (печатает count)
  python owning_channel.py channel-desc  -> обновить описание канала (тематические ссылки, без таро)
Анти-шаблон (inauthentic content): тема/хук/структура ротируются взаимно простыми длинами списков,
состояние .state/owning_idx.txt коммитит CI.
"""
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

TOPICS = [
    "car wash", "laundromat", "vending route", "self-storage facility",
    "small-town diner", "food truck", "ATM route", "mini golf course",
    "small-town gas station", "parking lot",
]  # 10
HOOKS = [
    "open with a surprising profit number",
    "open with a myth most people believe, then break it",
    "open with the hidden cost nobody mentions",
    "open with a direct question to the viewer",
    "open with a day-in-the-life moment of the owner",
    "open with a before/after: buying price vs. monthly cash",
    "open with a small-town story of one specific owner (fictional, say so)",
]  # 7, взаимно просто с 10
STRUCTURES = [
    "money in -> money out -> what's left",
    "three numbers that decide everything",
    "myth vs reality, beat by beat",
]  # 3
MAX_PER_DAY = 2
VOICE = "en-US-AndrewNeural"  # ponytail: один голос = узнаваемость канала; смена только через sample gate
MAX_SPEECH_WORDS = 150  # ~55 с при 165 wpm: Short <= 60 с

AI_NOTE = "AI-generated narration and visuals (synthetic content)."
DISCLAIMER = "Numbers are rough US estimates for illustration. Not financial advice."
HASHTAGS = "#Shorts #smallbusiness #businessideas #passiveincome"
# Решение владельца 18.10 (t_018254ae): таро-CTA на канале 1 нет нигде (аудитория не совпадает, вредит доверию).
# Только тематические ссылки; таро-воронка — на канале 2.
LINKS = "Free tools: SBA business plan guide https://www.sba.gov/business-guide/plan-your-business | SCORE free mentoring https://www.score.org"

PALETTES = [  # (фон, акцент, текст), по теме
    ("#0f1b2d", "#33d17a", "#ffffff"), ("#1d1023", "#ffb000", "#ffffff"), ("#0d2422", "#4fd1c5", "#ffffff"),
    ("#231a0d", "#ff7a45", "#ffffff"), ("#101820", "#f2c94c", "#ffffff"),
]
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".state"


def next_plan(state_dir: Path | None = None) -> dict:
    d = state_dir or STATE
    d.mkdir(parents=True, exist_ok=True)
    f = d / "owning_idx.txt"
    i = int(f.read_text()) if f.exists() else 0
    f.write_text(str(i + 1))
    return {"topic": TOPICS[i % len(TOPICS)], "hook": HOOKS[i % len(HOOKS)],
            "structure": STRUCTURES[i % len(STRUCTURES)], "idx": i}


def idea_prompt(plan: dict) -> str:
    return f"""You write scripts for the faceless YouTube Shorts channel "Economics of Owning" (US audience).
Today's video: The Economics of Owning a {plan['topic']}.
Hook style: {plan['hook']}.
Structure: {plan['structure']}.
Rules: 40-55 seconds of narration (110-145 words total), plain conversational US English, concrete
dollar figures that are realistic US ballparks (round them), no hype, no "smash that like button".
The first beat IS the hook (one short punchy sentence). The last beat is a one-line takeaway.
Return STRICT JSON only (no markdown) with fields:
  title: starts with "The Economics of Owning a" (or "an"), max 70 chars, may add a short hook after a colon
  hook: the first spoken sentence
  beats: list of 6-8 objects {{"say": one spoken sentence, "big": short on-screen figure like "$4M" or "25%",
         max 7 chars, "label": 1-4 word caption for the figure}}
  description: 2 sentences for the YouTube description
  tags: 6-10 English tags
"""


def parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def speech_words(s: dict) -> int:
    return len(" ".join([s.get("hook", "")] + [b["say"] for b in s["beats"]]).split())


def validate_script(s: dict) -> dict:
    if not re.match(r"^The Economics of Owning an? ", s.get("title", "")):
        raise ValueError(f"title вне формата: {s.get('title')!r}")
    beats = s.get("beats") or []
    if not 5 <= len(beats) <= 9 or not all(b.get("say") and b.get("big") for b in beats):
        raise ValueError(f"beats: нужно 5-9 с say/big, есть {len(beats)}")
    if speech_words(s) > MAX_SPEECH_WORDS:
        raise ValueError(f"слишком длинно для Short: {speech_words(s)} слов")
    s["title"] = s["title"][:100]
    return s


def short_description(s: dict) -> str:
    parts = [s.get("description", "").strip(), DISCLAIMER, AI_NOTE, HASHTAGS]
    return "\n\n".join(p for p in parts if p)


def channel_description() -> str:
    return ("What it really costs to own a car wash, a laundromat, a vending route and other small businesses "
            "in America. Real ballpark numbers, money in vs money out, no hype. New Shorts every day.\n\n"
            "Topics: small business economics, passive income reality checks, side hustle math, franchise and route "
            "costs, self-storage, laundromat and car wash profit breakdowns.\n\n"
            f"{DISCLAIMER}\n{AI_NOTE}\n\n{LINKS}")


def count_today(published_at: list[str], today: dt.date) -> int:
    return sum(1 for p in published_at if p[:10] == today.isoformat())


def count_owning_today(items: list[tuple[str, str]], today: dt.date) -> int:
    """(publishedAt, title): лимит слотов Owning не съедают ролики «What if» (ch2 живёт плейлистом на ch1)."""
    return count_today([p for p, t in items if t.startswith("The Economics of Owning")], today)


# ---------- render (TTS + инфографика) ----------

def _font(size, bold=True):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def _wrap(draw, text, font, width):
    lines, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if draw.textlength(t, font=font) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def card(path: Path, title: str, big: str, label: str, say: str, pal, step: int, total: int) -> None:
    from PIL import Image, ImageDraw
    bg, acc, fg = pal
    W, H = 1080, 1920
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    f_t, f_big, f_lab, f_say = _font(54), _font(230), _font(64), _font(56, bold=False)
    y = 170
    for ln in _wrap(d, title, f_t, W - 160):
        d.text((W / 2, y), ln, font=f_t, fill=fg, anchor="mm")
        y += 70
    d.rectangle([80, 520, W - 80, 1180], outline=acc, width=8)
    size = 230
    while d.textlength(big, font=f_big) > W - 220 and size > 100:
        size -= 20
        f_big = _font(size)
    d.text((W / 2, 800), big, font=f_big, fill=acc, anchor="mm")
    d.text((W / 2, 1060), label.upper(), font=f_lab, fill=fg, anchor="mm")
    y = 1290
    for ln in _wrap(d, say, f_say, W - 180)[:5]:  # субтитры: 85% смотрят без звука
        d.text((W / 2, y), ln, font=f_say, fill=fg, anchor="mm")
        y += 76
    bw = (W - 160) * (step + 1) / total  # прогресс-бар
    d.rectangle([80, 1780, 80 + bw, 1800], fill=acc)
    im.save(path)


def tts(text: str, out: Path) -> float:
    subprocess.run([sys.executable, "-m", "edge_tts", "--voice", VOICE, "--rate", "+6%",
                    "--text", text, "--write-media", str(out)], check=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                         capture_output=True, text=True, check=True).stdout
    return float(dur)


def render(run_dir: Path) -> Path:
    s = validate_script(json.loads((run_dir / "idea.json").read_text(encoding="utf-8")))
    pal = PALETTES[TOPICS.index(s["topic"]) % len(PALETTES)] if s.get("topic") in TOPICS else PALETTES[0]
    beats = s["beats"]
    if s.get("hook") and s["hook"].strip() != beats[0]["say"].strip():
        beats = [{"say": s["hook"], "big": beats[0]["big"], "label": beats[0].get("label", "")}] + beats
    w = run_dir / "owning"
    w.mkdir(exist_ok=True)
    segs, said = [], []
    for i, b in enumerate(beats):
        a, img, seg = w / f"{i:02d}.mp3", w / f"{i:02d}.png", w / f"{i:02d}.mp4"
        dur = tts(b["say"], a) + 0.25
        said.append((b["say"], dur))
        card(img, s["title"], b["big"], b.get("label", ""), b["say"], pal, i, len(beats))
        n = int(dur * 30)
        # лёгкий zoom-in: кадр не статичен
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(img), "-i", str(a),
                        "-filter_complex", f"[0:v]scale=1188:2112,zoompan=z='1+0.06*on/{n}':d={n}:s=1080x1920:fps=30"
                        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',format=yuv420p[v];[1:a]apad=pad_dur=0.25[a]",
                        "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                        "-c:a", "aac", "-ar", "44100", "-ac", "2", str(seg)], check=True)
        segs.append(seg)
    import localize
    localize.write_cues(run_dir / "cues.json", said)  # тайминги реплик для ES/PT субтитров (t_b9eb61b2)
    lst = w / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in segs))
    out = run_dir / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-af", "loudnorm=I=-14:TP=-1.5", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(out)], check=True)
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  str(out)], capture_output=True, text=True, check=True).stdout)
    if total > 60:
        raise SystemExit(f"Short длиннее 60 с: {total:.1f}")
    print(f"video -> {out} ({total:.1f}s, {len(beats)} beats)")
    return out


def _youtube():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from youtube_oauth import TOKEN_PATH
    return build("youtube", "v3", credentials=Credentials.from_authorized_user_file(str(TOKEN_PATH)))


def guard() -> int:
    y = _youtube()
    ch = y.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    try:
        items = y.playlistItems().list(part="snippet,contentDetails", playlistId=up, maxResults=30).execute().get("items", [])
    except Exception as e:  # пустой канал: uploads-плейлист ещё 404
        print(f"uploads list: {type(e).__name__}; считаю 0")
        items = []
    n = count_owning_today([(i["contentDetails"].get("videoPublishedAt", ""), i["snippet"].get("title", "")) for i in items],
                           dt.datetime.now(dt.timezone.utc).date())
    print(f"uploads today: {n}/{MAX_PER_DAY}")
    return 0 if n < MAX_PER_DAY else 3  # 3 = лимит (workflow: тихий пропуск), иное = ошибка


def set_channel_description() -> None:
    y = _youtube()
    ch = y.channels().list(part="brandingSettings", mine=True).execute()["items"][0]
    bs = ch["brandingSettings"]
    bs.setdefault("channel", {})["description"] = channel_description()
    y.channels().update(part="brandingSettings", body={"id": ch["id"], "brandingSettings": bs}).execute()
    print("channel description updated")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "render":
        from common import latest_run_dir
        render(latest_run_dir())
    elif cmd == "guard":
        sys.exit(guard())
    elif cmd == "channel-desc":
        set_channel_description()
    else:
        sys.exit(__doc__)
