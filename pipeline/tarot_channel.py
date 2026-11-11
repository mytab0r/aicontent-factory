#!/usr/bin/env python3
"""Таро-Shorts (канал «Луна | Таро», TikTok → pay.pxbt.app/tarot).

Генерация: случайный Major Arcana (public domain Rider-Waite из assets/tarot_cards),
скрипт через 9router, озвучка edge-tts, карточка 1080x1920 (PIL), ffmpeg-сборка.
  python tarot_channel.py render [runs_dir]  -> runs/<ts>/video.mp4
"""
import datetime as dt
import json
import random
import subprocess
import sys
from pathlib import Path

from quality_gate import LUFS_TARGET

ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = ROOT / "assets" / "tarot_cards"
VOICE = "en-US-AnaNeural"  # мягкий женский голос — таро-персона
MAX_SPEECH_WORDS = 90  # ~30-40 с

CARD_NAMES = {
    "00": "The Fool", "01": "The Magician", "02": "The High Priestess", "03": "The Empress",
    "04": "The Emperor", "05": "The Hierophant", "06": "The Lovers", "07": "The Chariot",
    "08": "Strength", "09": "The Hermit", "10": "Wheel of Fortune", "11": "Justice",
    "12": "The Hanged Man", "13": "Death", "14": "Temperance", "15": "The Devil",
    "16": "The Tower", "17": "The Star", "18": "The Moon", "19": "The Sun",
    "20": "Judgement", "21": "The World",
}
CARD_MEANINGS = {  # краткие, простые значения — для озвучки
    "00": "a leap into the unknown, taken with trust",
    "01": "the moment your will becomes the tool",
    "02": "knowledge that arrives before words do",
    "03": "something in you is ready to grow",
    "04": "structure holding steady when nothing else does",
    "05": "tradition, or the rules you inherited",
    "06": "a choice of the heart, not the mind",
    "07": "momentum that carries you forward",
    "08": "quiet strength, gentler than it looks",
    "09": "time alone that actually heals",
    "10": "the wheel turning — nothing stays fixed",
    "11": "the scales settling, exactly fair",
    "12": "seeing the world from a new angle",
    "13": "an ending that makes room",
    "14": "two opposites finding their mix",
    "15": "a chain you could loosen today",
    "16": "a sudden break that reveals the truth",
    "17": "hope returning after a long dark",
    "18": "the fog lifting, slowly, honestly",
    "19": "joy, warm and unhidden",
    "20": "a call you have been waiting for",
    "21": "completion — the circle closes",
}

HOOKS = [
    "The card that chose you today is {name}.",
    "I pulled one card for you. It's {name}.",
    "Today, the deck gave me {name} for you.",
]
CTA = "Your first full reading is free. The link is in my bio."

BG, ACC, FG = "#150f24", "#f2c94c", "#ffffff"  # ночной индиго / золото

IDEA_PROMPT = """You write 30-second tarot narration for a calm, mystical TikTok channel ("Луна | Таро").
The card drawn today is "{name}" — upright, meaning: {meaning}.
Rules: plain, warm, poetic but simple English. 55-80 words total. No hype, no "like and subscribe".
Structure: 1) a hook addressed to the viewer ("you"); 2) two short sentences of real interpretation
of this card; 3) one closing line inviting them back tomorrow.
Return STRICT JSON only: {{"title": "Tarot of the day: {name} (max 60 chars)",
"hook": "...", "lines": ["...", "...", "..."], "description": "1-2 sentences", "tags": ["tarot", ...]}}"""


def _run_ffmpeg(cmd: list) -> None:
    subprocess.run(cmd, check=True)


def tts(text: str, out: Path, sleep=None, tries=4, voice=VOICE) -> float:
    import time
    sleep = sleep or time.sleep
    for k in range(tries):
        try:
            subprocess.run([sys.executable, "-m", "edge_tts", "--voice", voice, "--rate", "-4%",
                            "--text", text, "--write-media", str(out)], check=True, capture_output=True, text=True)
            break
        except subprocess.CalledProcessError as e:
            err = (e.stderr or "").strip()[-400:]
            print(f"edge_tts {voice} attempt {k + 1}/{tries} rc={e.returncode}: {err}")
            if k == tries - 1:
                raise RuntimeError(f"edge_tts failed after {tries} tries: {err}") from e
            sleep(10 * (k + 1))
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout
    return float(dur)


def _font(size: int, bold: bool = True):
    from PIL import ImageFont
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _wrap(d, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def card_img(path: Path, title: str, card_png: Path, say: str, step: int, total: int) -> None:
    from PIL import Image, ImageDraw
    W, H = 1080, 1920
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    f_t, f_say = _font(48), _font(52, bold=False)
    y = 150
    for ln in _wrap(d, title, f_t, W - 140)[:2]:
        d.text((W / 2, y), ln, font=f_t, fill=FG, anchor="mm")
        y += 62
    # карта по центру, с золотой рамкой
    ci = Image.open(card_png).convert("RGB")
    ch = 900
    cw = int(ci.width * ch / ci.height)
    ci = ci.resize((cw, ch))
    x0 = (W - cw) // 2
    y0 = 380
    im.paste(ci, (x0, y0))
    d.rectangle([x0 - 12, y0 - 12, x0 + cw + 12, y0 + ch + 12], outline=ACC, width=6)
    y = y0 + ch + 90
    for ln in _wrap(d, say, f_say, W - 160)[:4]:
        d.text((W / 2, y), ln, font=f_say, fill=FG, anchor="mm")
        y += 68
    bw = (W - 160) * (step + 1) / total
    d.rectangle([80, 1780, 80 + bw, 1800], fill=ACC)
    im.save(path)


def idea(card_num: str, name: str, meaning: str) -> dict:
    """Скрипт через 9router; фолбэк — локальный шаблон без LLM."""
    from common import router_post
    prompt = IDEA_PROMPT.format(name=name, meaning=meaning)
    try:
        r = router_post("/v1/chat/completions", {"model": "auto-cheap-combo", "stream": False, "messages": [{"role": "user", "content": prompt}], "max_tokens": 400})
        txt = r["choices"][0]["message"]["content"]
        import re
        return json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    except Exception as e:
        print(f"router idea failed ({type(e).__name__}: {e}), fallback template")
        return {
            "title": f"Tarot of the day: {name}",
            "hook": random.choice(HOOKS).format(name=name),
            "lines": [
                f"{name} upright is {meaning}.",
                "This isn't a warning — it's a mirror.",
                "Sit with it. The card is speaking to where you are right now.",
            ],
            "description": f"{name} — tarot card of the day. Free first reading: link in bio.",
            "tags": ["tarot", "tarotreading", "dailytarot", name.replace(" ", "").lower()],
        }


def render(run_dir: Path) -> Path:
    random.seed()
    num = random.choice(list(CARD_NAMES))
    name = CARD_NAMES[num]
    s = idea(num, name, CARD_MEANINGS[num])
    (run_dir / "idea.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

    card_png = next(CARDS_DIR.glob(f"rws_{num}*.jpg"))
    spoken = [s["hook"]] + s["lines"][:2] + [CTA]
    words = sum(len(x.split()) for x in spoken)

    w = run_dir / "tarot"
    w.mkdir(exist_ok=True)
    segs = []
    for i, text in enumerate(spoken):
        a, img, seg = w / f"{i:02d}.mp3", w / f"{i:02d}.png", w / f"{i:02d}.mp4"
        dur = tts(text, a) + 0.25
        # первые 2 бита — карта открыта, дальше — обложка-тайтл
        card_img(img, s["title"], card_png if i < len(spoken) - 1 else card_png, text, i, len(spoken))
        n = int(dur * 30)
        _run_ffmpeg(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(img), "-i", str(a),
                     "-filter_complex", f"[0:v]zoompan=z='1+0.04*on/{n}':d={n}:s=1080x1920:fps=30"
                        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',format=yuv420p[v];"
                        f"[1:a]apad=pad_dur=0.25[a]",
                     "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                     "-threads", "2", "-c:a", "aac", "-ar", "44100", "-ac", "2", str(seg)])
        segs.append(seg)

    lst = w / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in segs))
    out = run_dir / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-af", f"loudnorm=I={LUFS_TARGET:g}:TP=-2.0", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    str(out)], check=True)
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                  "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout)
    if total > 60:
        raise SystemExit(f"Short longer than 60s: {total:.1f}")
    print(f"video -> {out} ({total:.1f}s, card={name})")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "render"
    if cmd == "render":
        ts = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
        run_dir = Path(sys.argv[2] if len(sys.argv) > 2 else ROOT / "runs" / ts)
        run_dir.mkdir(parents=True, exist_ok=True)
        render(run_dir)
    else:
        raise SystemExit("usage: tarot_channel.py render [runs_dir]")
