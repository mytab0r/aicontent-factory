#!/usr/bin/env python3
"""S1 ch2 «What if...» — режим code-2D: 2D-анимацию рисует код, синхронно с пословными таймкодами TTS.

Флаг: CODE2D=1 (repo var CODE2D в workflow). Выключен = все команды no-op с exit 0 (откат = снять флаг).
  python whatif_channel.py idea     -> runs/<new>/idea.json (2 стадии LLM через 9router: сценарий, затем DSL сцен)
  python whatif_channel.py render   -> runs/<last>/long.mp4 (1920x1080) + short_1..3.mp4 (1080x1920) + cover.png
  python whatif_channel.py publish  -> YouTube: long + 3 Shorts в плейлист «What If...», runs/<last>/published.json
Сцена = DSL (персонажи-примитивы, действия привязаны к индексу слова реплики); рендер = Pillow -> ffmpeg pipe.
Свой визуальный язык: «пилюли» с точками-глазами на плоских силуэтных фонах, караоке-субтитр.
Анти-шаблон: тема/угол/палитра ротируются взаимно простыми длинами, состояние .state/whatif_idx.txt коммитит CI.
"""
import json
import math
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from quality_gate import LUFS_TARGET

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".state"
FPS = 24
VOICE = "en-US-GuyNeural"  # ponytail: один голос канала (не Andrew с ch1); смена через sample gate
MIN_WORDS = 620  # ~4.2 мин при ~150 wpm: long >= 4 мин
SHORT_LIMIT = 58.0
PLAYLIST = "What If..."
AI_NOTE = "AI-generated narration and code-drawn animation (synthetic content)."
HASHTAGS = "#whatif #thoughtexperiment #animation"

TOPICS = [
    "you never felt fear", "you could hear everyone's thoughts for one day", "humans needed only one hour of sleep",
    "money disappeared overnight", "you lived exactly one hundred years longer", "the internet shut down for a year",
    "you could never lie again", "everyone on Earth jumped at the same time", "you remembered every second of your life",
    "gravity got ten percent weaker", "you woke up as the only person left", "nobody could feel pain",
    "you could pause time for ten minutes a day",
]  # 13
ANGLES = [
    "walk through the first hour, first day, first week, first year",
    "tell it as one ordinary person's story, then zoom out to the whole world",
    "the good news first, then the hidden cost nobody expects",
    "start with a vivid moment, then explain the real science behind it",
]  # 4, взаимно просто с 13
PALETTES = [  # (небо, земля, акцент, текст, силуэты)
    ("#14213d", "#1f2f52", "#fca311", "#ffffff", "#0d1730"),
    ("#2b193d", "#3d2556", "#ff5d8f", "#ffffff", "#1c1029"),
    ("#0b3d3a", "#11524e", "#f9c74f", "#ffffff", "#072826"),
    ("#3a2618", "#4f3421", "#90e0ef", "#ffffff", "#24170e"),
    ("#1b1b1b", "#2a2a2a", "#7cff6b", "#ffffff", "#0f0f0f"),
]  # 5
PLACES = ["city", "home", "nature", "space", "office", "ocean", "void"]
PROPS = ["heart", "star", "coin", "cloud", "bolt", "clock", "question", "exclaim", "sun", "moon", "house", "tree", "phone"]
MOODS = ["happy", "sad", "scared", "shocked", "calm", "angry"]
ACTIONS = {"walk", "jump", "shake", "grow", "shrink", "spawn", "pop", "say", "mood", "hide", "show"}
NEEDS_WHO = {"walk", "jump", "shake", "grow", "shrink", "say", "mood", "hide", "show"}


def settings() -> dict:
    """Параметры выпуска из env (repo vars). WHATIF_LEGACY=1 = откат одним изменением к поведению до t_47c41540."""
    if os.environ.get("WHATIF_LEGACY", "").strip() == "1":
        return {"hook": False, "short_max": SHORT_LIMIT, "short_min": 0.0, "long_every": 1}
    try:
        short_max = min(SHORT_LIMIT, max(15.0, float(os.environ.get("WHATIF_SHORT_MAX", "30"))))
    except ValueError:
        short_max = 30.0
    try:
        long_every = max(1, int(os.environ.get("WHATIF_LONG_EVERY", "2")))
    except ValueError:
        long_every = 2
    return {"hook": os.environ.get("WHATIF_HOOK", "1").strip() != "0", "short_max": short_max,
            "short_min": min(20.0, short_max), "long_every": long_every}


def long_due(idx: int, every: int) -> bool:
    """Long — 1 раз в `every` выпусков (выпуск = 1/день); Shorts выходят каждый день."""
    return idx % max(1, every) == 0


def render_workers(jobs: int, cpus: int | None = None) -> int:
    # ponytail: потолок 6 процессов (каждый = Pillow + ffmpeg x264); 19.10 32 параллельных рендера на общем
    # раннере уронили ffmpeg (BrokenPipe). Поднять, если раннер станет выделенным.
    return max(1, min(jobs, cpus or os.cpu_count() or 2, 6))


def hook_text(title: str) -> str:
    t = title.strip()
    return t if re.match(r"^What if\b", t, re.I) else f"What if {t.rstrip('?')}?"


def hook_scale(t: float, dur: float = 1.0) -> float:
    """Масштаб хука: наезд 0.7 -> 1.0 за 0.6 с (движение в первую секунду), после `dur` — 0 (хука нет)."""
    return 0.0 if t > dur else 0.7 + 0.3 * _ease(t / 0.6)


def enabled() -> bool:
    return os.environ.get("CODE2D", "").strip().lower() in ("1", "true", "yes", "on")


# ---------- план и сценарий ----------

def next_plan(state_dir: Path | None = None) -> dict:
    d = state_dir or STATE
    d.mkdir(parents=True, exist_ok=True)
    f = d / "whatif_idx.txt"
    i = int(f.read_text()) if f.exists() else 0
    f.write_text(str(i + 1))
    return {"topic": TOPICS[i % len(TOPICS)], "angle": ANGLES[i % len(ANGLES)], "palette": i % len(PALETTES), "idx": i}


def script_prompt(plan: dict) -> str:
    return f"""You write narration for a faceless YouTube channel of animated thought experiments.
Video: "What if {plan['topic']}?"  Angle: {plan['angle']}.
Rules: 4.5-5.5 minutes of narration = 700-820 words in total, plain vivid US English, second person ("you"),
grounded in real science or psychology where possible, no hype, no "like and subscribe". Spell numbers as words.
Split into 12-14 scenes of 45-70 words each. Scene 1 opens with the question as a hook. Last scene = one-line takeaway.
Return STRICT JSON only:
  title: starts with "What if", max 70 chars
  description: 2 sentences for YouTube
  tags: 6-10 English tags
  characters: 1-3 objects {{"id": short lowercase id, "label": 1-2 word name, "color": "#rrggbb"}} (first one is "you")
  scenes: list of {{"place": one of {PLACES}, "text": narration of the scene}}
"""


def scene_prompt(sc: dict, characters: list) -> str:
    words = sc["text"].split()
    numbered = " ".join(f"[{i}]{w}" for i, w in enumerate(words))
    return f"""You animate one scene of a 2D cartoon with code. Characters are simple shapes: {json.dumps(characters)}.
Narration with word indices: {numbered}
Return STRICT JSON only: {{"cast": [{{"id": id, "x": 0.1-0.9, "mood": one of {MOODS}}}],
 "actions": [{{"word": index of the word when it happens, "do": one of {sorted(ACTIONS)}, ...}}]}}
Action fields: walk {{who, x}}; jump/shake/grow/shrink/hide/show {{who}}; mood {{who, mood}}; say {{who, text<=4 words}};
spawn {{prop: one of {PROPS}, x: 0.1-0.9, y: 0.15-0.6}}; pop {{prop}}.
Make 5-9 actions spread over the whole narration, each tied to the word that motivates it (e.g. spawn coin on "money").
"""


def parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def _hex(c, default):
    return c if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) else default


def _f(v, lo, hi, default):
    try:
        return min(hi, max(lo, float(v)))
    except (TypeError, ValueError):
        return default


def validate_script(s: dict) -> dict:
    """Нормализует DSL (недоверенный вывод LLM): неизвестное выбрасывается/зажимается, рендер не падает."""
    if not re.match(r"^What if\b", s.get("title", ""), re.I):
        raise ValueError(f"title вне формата: {s.get('title')!r}")
    scenes = s.get("scenes") or []
    if len(scenes) < 8:
        raise ValueError(f"сцен {len(scenes)} < 8")
    words = sum(len(str(sc.get("text", "")).split()) for sc in scenes)
    if words < MIN_WORDS:
        raise ValueError(f"слов {words} < {MIN_WORDS}: long < 4 мин")
    chars = [c for c in (s.get("characters") or []) if isinstance(c, dict) and c.get("id")][:3] or [{"id": "you"}]
    defaults = ["#ffb000", "#4cc9f0", "#f72585"]
    s["characters"] = [{"id": str(c["id"]), "label": str(c.get("label") or c["id"])[:14],
                        "color": _hex(c.get("color"), defaults[i])} for i, c in enumerate(chars)]
    ids = {c["id"] for c in s["characters"]}
    for sc in scenes:
        n = len(str(sc.get("text", "")).split())
        if sc.get("place") not in PLACES:
            sc["place"] = PLACES[sum(map(ord, str(sc.get("place")))) % len(PLACES)]
        sc["cast"] = [{"id": c["id"], "x": _f(c.get("x"), 0.1, 0.9, 0.5), "mood": c.get("mood") if c.get("mood") in MOODS else "calm"}
                      for c in (sc.get("cast") or []) if isinstance(c, dict) and c.get("id") in ids][:3]
        acts = []
        for a in sc.get("actions") or []:
            if not isinstance(a, dict) or a.get("do") not in ACTIONS:
                continue
            if a["do"] in NEEDS_WHO and a.get("who") not in ids:
                continue
            a = dict(a, word=int(_f(a.get("word"), 0, max(0, n - 1), 0)))
            if a["do"] in ("spawn", "pop") and a.get("prop") not in PROPS:
                a["prop"] = PROPS[sum(map(ord, str(a.get("prop")))) % len(PROPS)]
            if a["do"] == "mood" and a.get("mood") not in MOODS:
                a["mood"] = "shocked"
            a["say_text"] = str(a.pop("text", ""))[:28]
            acts.append(a)
        sc["actions"] = sorted(acts, key=lambda a: a["word"])
    s["title"] = s["title"][:100]
    return s


LEXICON = {  # слово реплики -> реквизит (фолбэк-аниматор, когда DSL от LLM не пришёл)
    "coin": ("money", "dollar", "cash", "rich", "pay", "price", "cost", "bank", "salary"),
    "clock": ("time", "hour", "minute", "second", "year", "day", "week", "clock", "late", "morning", "night"),
    "heart": ("love", "heart", "partner", "friend", "kiss", "care", "family"),
    "bolt": ("energy", "power", "shock", "brain", "electric", "fast", "signal", "nerve"),
    "phone": ("phone", "internet", "online", "message", "email", "screen", "app"),
    "house": ("home", "house", "room", "bed", "neighbor", "city"),
    "tree": ("tree", "forest", "nature", "plant", "grow"),
    "sun": ("sun", "light", "summer", "warm", "wake"),
    "moon": ("moon", "sleep", "dream", "dark"),
    "star": ("star", "space", "universe", "planet", "famous"),
    "cloud": ("cloud", "rain", "weather", "think", "thought", "mind", "voice"),
    "exclaim": ("fear", "danger", "scream", "panic", "suddenly", "never", "die", "death"),
    "question": ("why", "how", "what", "wonder", "maybe", "strange"),
}
MOOD_WORDS = {"scared": ("afraid", "fear", "scared", "panic", "terrified"), "happy": ("happy", "joy", "laugh", "smile", "love"),
              "sad": ("sad", "alone", "lonely", "cry", "lost"), "shocked": ("shock", "suddenly", "wow", "realize"),
              "angry": ("angry", "rage", "fight", "argue")}


def auto_actions(text: str, cast: list, limit: int = 8) -> list:
    """Детерминированные действия по ключевым словам реплики: каждое привязано к индексу своего слова."""
    who = [c["id"] for c in cast] or ["you"]
    acts, used, k = [], set(), 0
    for i, w in enumerate(text.split()):
        n = re.sub(r"[^a-z]", "", w.lower())
        prop = next((p for p, ws in LEXICON.items() if any(n.startswith(x) for x in ws)), None)
        mood = next((m for m, ws in MOOD_WORDS.items() if any(n.startswith(x) for x in ws)), None)
        if mood:
            acts.append({"word": i, "do": "mood", "who": who[k % len(who)], "mood": mood})
            k += 1
        elif prop and prop not in used:
            used.add(prop)
            acts.append({"word": i, "do": "spawn", "prop": prop, "x": 0.15 + 0.7 * ((len(used) * 0.37) % 1), "y": 0.25})
        elif w.endswith((".", "!", "?")) and i + 1 < len(text.split()):
            acts.append({"word": i + 1, "do": ("jump", "walk", "shake")[k % 3], "who": who[k % len(who)],
                         "x": 0.25 + 0.5 * (k % 2)})
            k += 1
    if len(acts) > limit:  # равномерно прореживаем, порядок слов сохраняется
        acts = [acts[round(j * (len(acts) - 1) / (limit - 1))] for j in range(limit)]
    return acts


# ---------- синхронизация ----------

def word_time(bounds: list, idx: int, n_text: int) -> float:
    """Время начала idx-го слова текста по границам TTS; при расхождении счёта слов — пропорционально."""
    if not bounds:
        return 0.0
    j = idx if n_text == len(bounds) else int(idx * len(bounds) / max(1, n_text))
    return bounds[min(j, len(bounds) - 1)][0]


def _norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def align(tokens: list, bounds: list) -> list:
    """Время каждого слова текста: точное совпадение с границей TTS (окно 3), иначе пропорция."""
    out, j = [], 0
    for i, t in enumerate(tokens):
        hit = next((k for k in range(j, min(j + 3, len(bounds))) if _norm(bounds[k][2]) == _norm(t)), None)
        if hit is not None:
            out.append(bounds[hit][0])
            j = hit + 1
        else:
            out.append(max(out[-1] if out else 0.0, word_time(bounds, i, len(tokens))))
    return out


def timeline(sc: dict, bounds: list) -> dict:
    toks = sc["text"].split()
    times = align(toks, bounds)
    end = bounds[-1][1] if bounds else 0.0
    ev = [dict(a, t=(times[a["word"]] if a["word"] < len(times) else end)) for a in sc["actions"]]
    return {"cast": {c["id"]: c for c in sc["cast"]}, "events": sorted(ev, key=lambda e: e["t"])}


def _ease(p):
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def char_state(tl: dict, cid: str, t: float) -> dict:
    base = tl["cast"].get(cid)
    st = {"x": base["x"] if base else 0.5, "dx": 0.0, "dy": 0.0, "scale": 1.0, "mood": base["mood"] if base else "calm",
          "visible": base is not None, "say": "", "pop": 1.0}
    for e in tl["events"]:
        if e.get("who") != cid or e["t"] > t:
            continue
        dt_ = t - e["t"]
        d = e["do"]
        if d == "walk":
            st["x"] += (_f(e.get("x"), 0.1, 0.9, st["x"]) - st["x"]) * _ease(dt_ / 0.9)
        elif d == "jump" and dt_ < 0.6:
            st["dy"] = -0.12 * math.sin(math.pi * dt_ / 0.6)
        elif d == "shake" and dt_ < 0.6:
            st["dx"] = 0.012 * math.sin(dt_ * 50)
        elif d in ("grow", "shrink"):
            st["scale"] *= 1 + (0.35 if d == "grow" else -0.3) * _ease(dt_ / 0.5)
        elif d == "mood":
            st["mood"] = e["mood"]
        elif d == "say" and dt_ < 1.8:
            st["say"] = e.get("say_text", "")
        elif d in ("hide", "show"):
            if d == "show" and not st["visible"]:
                st["pop"] = _ease(dt_ / 0.4)
            st["visible"] = d == "show"
    if not base and not st["visible"]:
        return st
    return st


def props_at(tl: dict, t: float) -> list:
    live = {}
    for e in tl["events"]:
        if e["t"] > t:
            break
        if e["do"] == "spawn":
            live[e["prop"]] = {"prop": e["prop"], "x": _f(e.get("x"), 0.1, 0.9, 0.5), "y": _f(e.get("y"), 0.15, 0.6, 0.35),
                               "k": _ease((t - e["t"]) / 0.35), "t0": e["t"]}
        elif e["do"] == "pop":
            live.pop(e["prop"], None)
    return list(live.values())


def caption_at(bounds: list, t: float, chunk: int = 6):
    """(слова окна, индекс звучащего слова) для караоке-субтитра."""
    if not bounds:
        return [], -1
    i = max([k for k, b in enumerate(bounds) if b[0] <= t] or [0])
    s = 0  # окна по <= chunk слов, новое окно и после конца фразы (эвристика: следующее слово с заглавной)
    for k in range(1, i + 1):
        if k - s >= chunk or (bounds[k][2][:1].isupper() and bounds[k][2] != "I"):
            s = k
    e = s + 1
    while e < len(bounds) and e - s < chunk and not (bounds[e][2][:1].isupper() and bounds[e][2] != "I"):
        e += 1
    return [b[2] for b in bounds[s:e]], i - s


def short_windows(durs: list, n: int = 3, limit: float = SHORT_LIMIT, floor: float = 0.0) -> list:
    """n разных непрерывных окон сцен длиной [floor, limit] с: подряд с начала, добор — с других стартов.
    Не набралось n: добор окнами без floor, затем окнами <= SHORT_LIMIT (выпуск не падает)."""
    def win(s, lim):
        tot, e = 0.0, s
        while e < len(durs) and tot + durs[e] <= lim:
            tot += durs[e]
            e += 1
        return list(range(s, e)) if e > s else None
    out = []
    for lim, fl in ((limit, floor), (limit, 0.0), (max(limit, SHORT_LIMIT), 0.0)):
        s = 0
        while s < len(durs) and len(out) < n:  # непересекающиеся подряд
            w = win(s, lim)
            if w and sum(durs[i] for i in w) >= fl and not any(set(w) & set(o) for o in out):
                out.append(w)
                s = w[-1] + 1
            else:
                s += 1
        for s in range(len(durs)):  # добор с других стартов
            if len(out) >= n:
                break
            w = win(s, lim)
            if w and sum(durs[i] for i in w) >= fl and w not in out:
                out.append(w)
        if len(out) >= n:
            break
    return out[:n]


# ---------- рисование ----------

def _font(size, bold=True):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def backdrop(place: str, pal, W: int, H: int, ground: float):
    from PIL import Image, ImageDraw
    sky, gnd, acc, _, sil = pal
    im = Image.new("RGB", (W, H), sky)
    d = ImageDraw.Draw(im)
    gy = int(H * ground)
    u = min(W, H)
    if place == "city":
        x = 0
        while x < W:
            w = int(u * (0.08 + 0.05 * ((x * 7) % 3)))
            h = int(u * (0.18 + 0.12 * ((x * 13) % 4) / 3))
            d.rectangle([x, gy - h, x + w - 6, gy], fill=sil)
            for wy in range(gy - h + 14, gy - 20, 28):
                for wx in range(x + 10, x + w - 18, 22):
                    if (wx + wy) % 3 == 0:
                        d.rectangle([wx, wy, wx + 8, wy + 12], fill=acc)
            x += w
    elif place == "home":
        d.rectangle([int(W * 0.12), int(H * 0.12), int(W * 0.32), int(H * 0.12 + u * 0.22)], outline=acc, width=6)
        d.line([int(W * 0.22), int(H * 0.12), int(W * 0.22), int(H * 0.12 + u * 0.22)], fill=acc, width=4)
        d.rectangle([int(W * 0.7), gy - int(u * 0.12), int(W * 0.9), gy], fill=sil)
    elif place == "nature":
        for k, (cx, r) in enumerate(((0.2, 0.5), (0.65, 0.65), (1.0, 0.45))):
            d.ellipse([int(W * cx - u * r), gy - int(u * r * 0.45), int(W * cx + u * r), gy + int(u * r * 0.45)], fill=sil)
    elif place == "space":
        for k in range(90):
            x, y = (k * 7919) % W, (k * 104729) % gy
            d.ellipse([x, y, x + 3, y + 3], fill="#ffffff")
        r = int(u * 0.09)
        d.ellipse([int(W * 0.8) - r, int(H * 0.2) - r, int(W * 0.8) + r, int(H * 0.2) + r], fill=acc)
    elif place == "office":
        for k in range(3):
            x = int(W * (0.1 + 0.32 * k))
            d.rectangle([x, gy - int(u * 0.09), x + int(u * 0.22), gy - int(u * 0.075)], fill=sil)
            d.rectangle([x + int(u * 0.06), gy - int(u * 0.17), x + int(u * 0.15), gy - int(u * 0.1)], outline=acc, width=4)
    elif place == "ocean":
        for k in range(6):
            y = gy - int(u * 0.03 * k)
            d.arc([-40 + (k % 2) * 60, y - 20, W + 40, y + 60], 200, 340, fill=acc, width=3)
    d.rectangle([0, gy, W, H], fill=gnd)
    return im


def draw_prop(d, kind, cx, cy, r, acc, fg):
    if r < 2:
        return
    if kind == "heart":
        d.ellipse([cx - r, cy - r * .6, cx, cy + r * .2], fill="#ff4d6d")
        d.ellipse([cx, cy - r * .6, cx + r, cy + r * .2], fill="#ff4d6d")
        d.polygon([(cx - r * .95, cy - r * .05), (cx + r * .95, cy - r * .05), (cx, cy + r)], fill="#ff4d6d")
    elif kind == "star":
        pts = [(cx + r * (1 if k % 2 == 0 else .45) * math.sin(k * math.pi / 5), cy - r * (1 if k % 2 == 0 else .45) * math.cos(k * math.pi / 5)) for k in range(10)]
        d.polygon(pts, fill="#ffd166")
    elif kind == "coin":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#ffd166", outline="#b8860b", width=max(2, int(r / 8)))
        d.text((cx, cy), "$", font=_font(int(r * 1.2)), fill="#b8860b", anchor="mm")
    elif kind == "cloud":
        for ox, oy, rr in ((-.5, .1, .5), (0, -.2, .6), (.5, .1, .5)):
            d.ellipse([cx + ox * r - rr * r, cy + oy * r - rr * r, cx + ox * r + rr * r, cy + oy * r + rr * r], fill="#e9ecef")
    elif kind == "bolt":
        d.polygon([(cx + r * .2, cy - r), (cx - r * .5, cy + r * .1), (cx, cy + r * .1), (cx - r * .2, cy + r),
                   (cx + r * .5, cy - r * .1), (cx, cy - r * .1)], fill="#ffd60a")
    elif kind == "clock":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fg, outline=acc, width=max(3, int(r / 8)))
        d.line([cx, cy, cx, cy - r * .7], fill="#222", width=max(3, int(r / 10)))
        d.line([cx, cy, cx + r * .5, cy], fill="#222", width=max(3, int(r / 10)))
    elif kind in ("question", "exclaim"):
        d.text((cx, cy), "?" if kind == "question" else "!", font=_font(int(r * 2)), fill=acc, anchor="mm")
    elif kind == "sun":
        for k in range(8):
            a = k * math.pi / 4
            d.line([cx + r * .8 * math.cos(a), cy + r * .8 * math.sin(a), cx + r * 1.3 * math.cos(a), cy + r * 1.3 * math.sin(a)], fill="#ffb703", width=max(3, int(r / 8)))
        d.ellipse([cx - r * .7, cy - r * .7, cx + r * .7, cy + r * .7], fill="#ffb703")
    elif kind == "moon":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#f1faee")
        d.ellipse([cx - r * .4, cy - r * 1.1, cx + r * 1.4, cy + r * .7], fill=None, outline=None)
    elif kind == "house":
        d.rectangle([cx - r * .7, cy - r * .1, cx + r * .7, cy + r], fill="#adb5bd")
        d.polygon([(cx - r, cy - r * .05), (cx + r, cy - r * .05), (cx, cy - r)], fill=acc)
    elif kind == "tree":
        d.rectangle([cx - r * .12, cy, cx + r * .12, cy + r], fill="#8d5524")
        d.ellipse([cx - r * .7, cy - r, cx + r * .7, cy + r * .2], fill="#52b788")
    elif kind == "phone":
        d.rounded_rectangle([cx - r * .5, cy - r, cx + r * .5, cy + r], radius=int(r * .15), fill="#212529", outline=fg, width=3)
        d.rectangle([cx - r * .4, cy - r * .8, cx + r * .4, cy + r * .7], fill=acc)


def draw_char(d, c, st, W, H, gy, u, fg):
    if not st["visible"]:
        return
    s = st["scale"] * st["pop"]
    bw, bh = u * 0.11 * s, u * 0.2 * s
    cx = (st["x"] + st["dx"]) * W
    by = gy + st["dy"] * H
    d.ellipse([cx - bw * .8, gy - u * .012, cx + bw * .8, gy + u * .012], fill="#00000055")
    d.rounded_rectangle([cx - bw / 2, by - bh, cx + bw / 2, by], radius=int(bw / 2), fill=c["color"])
    ey, ex, er = by - bh * .72, bw * .2, max(2, bw * .08)
    m = st["mood"]
    if m == "shocked":
        er *= 1.6
    for sx in (-1, 1):
        d.ellipse([cx + sx * ex - er, ey - er, cx + sx * ex + er, ey + er], fill="#111111")
    my, mw = by - bh * .52, bw * .22
    box = [cx - mw, my - mw * .6, cx + mw, my + mw * .6]
    if m == "happy":
        d.arc(box, 20, 160, fill="#111111", width=max(2, int(bw / 18)))
    elif m == "sad":
        d.arc([box[0], box[1] + mw * .6, box[2], box[3] + mw * .6], 200, 340, fill="#111111", width=max(2, int(bw / 18)))
    elif m in ("shocked", "scared"):
        d.ellipse([cx - mw * .4, my - mw * .2, cx + mw * .4, my + mw * .6], fill="#111111")
        if m == "scared":
            for sx in (-1, 1):
                d.line([cx + sx * bw * .62, by - bh * .9, cx + sx * bw * .7, by - bh * .7], fill=fg, width=3)
    elif m == "angry":
        for sx in (-1, 1):
            d.line([cx + sx * ex * 1.8, ey - er * 2.5, cx + sx * ex * .4, ey - er * 1.4], fill="#111111", width=max(2, int(bw / 18)))
        d.line([cx - mw, my, cx + mw, my], fill="#111111", width=max(2, int(bw / 18)))
    else:
        d.line([cx - mw * .7, my, cx + mw * .7, my], fill="#111111", width=max(2, int(bw / 20)))
    d.text((cx, by + u * .035), c["label"], font=_font(max(12, int(u * .026))), fill=fg, anchor="mm")
    if st["say"]:
        f = _font(max(14, int(u * .032)))
        tw = d.textlength(st["say"], font=f)
        bx, byy = min(max(cx, tw / 2 + 30), W - tw / 2 - 30), by - bh - u * .07
        d.rounded_rectangle([bx - tw / 2 - 18, byy - u * .03, bx + tw / 2 + 18, byy + u * .03], radius=14, fill="#ffffff")
        d.text((bx, byy), st["say"], font=f, fill="#111111", anchor="mm")


def draw_hook(d, text, t, W, H, acc, sec=1.0, size=.11):
    """Хук 0-1 с: вопрос «What if…» крупно по центру, наезд (движение в кадре с первого кадра)."""
    k = hook_scale(t, sec)
    if not k:
        return
    u = min(W, H)
    f = _font(max(16, int(u * size * k)))
    lines, cur = [], ""
    for w in text.split():  # перенос по ширине 86%
        if cur and d.textlength(f"{cur} {w}", font=f) > W * .86:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    lh = f.size * 1.2
    y0 = H * .4 - lh * len(lines) / 2
    tw = max(d.textlength(x, font=f) for x in lines)
    d.rounded_rectangle([(W - tw) / 2 - 30, y0 - 24, (W + tw) / 2 + 30, y0 + lh * len(lines) + 24], radius=28, fill=acc)
    for j, x in enumerate(lines):
        d.text((W / 2, y0 + lh * (j + .5)), x, font=f, fill="#111111", anchor="mm")


def draw_frame(bg, sc, tl, bounds, t, pal, characters, W, H, gy, banner, hook="", hook_sec=1.0, hook_size=.11):
    from PIL import ImageDraw
    im = bg.copy()
    d = ImageDraw.Draw(im, "RGBA")
    _, _, acc, fg, _ = pal
    u = min(W, H)
    for p in props_at(tl, t):
        bob = math.sin((t - p["t0"]) * 2.2) * u * .008
        draw_prop(d, p["prop"], p["x"] * W, p["y"] * gy + bob, u * .055 * p["k"], acc, fg)
    for c in characters:
        draw_char(d, c, char_state(tl, c["id"], t), W, H, gy, u, fg)
    words, cur = caption_at(bounds, t)
    if words:
        f = _font(int(u * (.05 if W > H else .055)))
        line = " ".join(words)
        tw = d.textlength(line, font=f)
        while tw > W * .9 and f.size > 18:
            f = _font(f.size - 4)
            tw = d.textlength(line, font=f)
        x, y = (W - tw) / 2, H * (.89 if W > H else .8)
        for k, w in enumerate(words):
            col = acc if k == cur else fg
            d.text((x + 2, y + 2), w, font=f, fill="#000000aa", anchor="lm")
            d.text((x, y), w, font=f, fill=col, anchor="lm")
            x += d.textlength(w + " ", font=f)
    if banner:
        f = _font(int(u * (.034 if W > H else .05)))
        while d.textlength(banner, font=f) > W * .86 and f.size > 16:
            f = _font(f.size - 2)
        bw_ = d.textlength(banner, font=f)
        y0 = H * (.06 if W > H else .1)
        d.rounded_rectangle([(W - bw_) / 2 - 24, y0 - u * .035, (W + bw_) / 2 + 24, y0 + u * .035], radius=18, fill=acc)
        d.text((W / 2, y0), banner, font=f, fill="#111111", anchor="mm")
    if hook:
        draw_hook(d, hook, t, W, H, acc, hook_sec, hook_size)
    return im


def render_scene(sc, bounds, audio, dur, pal, characters, out, W, H, banner="", hook="", hook_sec=1.0, hook_size=.11):
    """Кадры Pillow -> ffmpeg rawvideo pipe + аудио сцены -> mp4 (h264/aac)."""
    gy = int(H * (.74 if W > H else .64))
    bg = backdrop(sc["place"], pal, W, H, gy / H)
    tl = timeline(sc, bounds)
    n = max(1, math.ceil(dur * FPS))
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-i", str(audio), "-af", f"apad=whole_dur={dur:.3f}",
                          "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-threads", "2",
                          "-c:a", "aac", "-ar", "44100", "-ac", "2", "-t", f"{dur:.3f}", str(out)],
                         stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for k in range(n):
            p.stdin.write(draw_frame(bg, sc, tl, bounds, k / FPS, pal, characters, W, H, gy, banner, hook,
                                        hook_sec, hook_size).tobytes())
    except BrokenPipeError:
        pass  # ffmpeg умер: причина — в его stderr ниже
    finally:
        try:
            p.stdin.close()
        except BrokenPipeError:
            pass
    err = p.stderr.read().decode(errors="replace")[-600:]
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg scene render failed (rc={p.returncode}): {out}: {err}")
    return out


# ---------- TTS / сборка ----------

def tts(text: str, out: Path) -> tuple[list, float]:
    """edge-tts (бесплатно) с пословными границами: [(start, end, word)], длительность."""
    import asyncio
    import edge_tts

    async def go():
        bounds = []
        c = edge_tts.Communicate(text, VOICE, rate="+4%", boundary="WordBoundary")
        with open(out, "wb") as f:
            async for ch in c.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    s = ch["offset"] / 1e7
                    bounds.append((s, s + ch["duration"] / 1e7, ch["text"]))
        return bounds
    for attempt in range(3):
        try:
            bounds = asyncio.run(go())
            break
        except Exception as e:  # сетевой сбой edge-tts
            print(f"tts retry {attempt + 1}: {type(e).__name__}")
            if attempt == 2:
                raise
    return bounds, probe(out)


def probe(path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True, check=True).stdout)


def _render_job(args):
    return str(render_scene(*args))


def concat(parts: list, out: Path) -> Path:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{Path(p).resolve()}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-af", f"loudnorm=I={LUFS_TARGET:g}:TP=-2.0", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(out)], check=True)
    return out


def render(run_dir: Path) -> dict:
    from PIL import ImageDraw
    s = validate_script(json.loads((run_dir / "idea.json").read_text(encoding="utf-8")))
    pal = PALETTES[s.get("plan", {}).get("palette", 0) % len(PALETTES)]
    w = run_dir / "code2d"
    w.mkdir(exist_ok=True)
    with ThreadPoolExecutor(6) as ex:  # TTS — сеть, параллельно
        tt = list(ex.map(lambda i: tts(s["scenes"][i]["text"], w / f"{i:02d}.mp3"), range(len(s["scenes"]))))
    durs = [d + 0.45 for _, d in tt]
    (w / "timing.json").write_text(json.dumps([{"dur": d, "bounds": b} for (b, _), d in zip(tt, durs)]))
    cfg = settings()
    with_long = long_due(int(s.get("plan", {}).get("idx", 0)), cfg["long_every"])
    wins = short_windows(durs, limit=cfg["short_max"], floor=cfg["short_min"])
    hook = hook_text(s["title"]) if cfg["hook"] else ""
    jobs = [(sc, tt[i][0], w / f"{i:02d}.mp3", durs[i], pal, s["characters"], w / f"L{i:02d}.mp4", 1920, 1080, "")
            for i, sc in enumerate(s["scenes"])] if with_long else []
    firsts = {win[0] for win in wins} if hook else set()
    vert = sorted({(i, i in firsts and j == 0) for win in wins for j, i in enumerate(win)})
    vname = lambda i, h: w / f"V{i:02d}{'h' if h else ''}.mp4"  # noqa: E731  h = вариант сцены с хуком
    jobs += [(s["scenes"][i], tt[i][0], w / f"{i:02d}.mp3", durs[i], pal, s["characters"], vname(i, h), 1080, 1920,
              s["title"], hook if h else "") for i, h in vert]
    with ProcessPoolExecutor(render_workers(len(jobs))) as ex:
        list(ex.map(_render_job, jobs))
    long = concat([w / f"L{i:02d}.mp4" for i in range(len(s["scenes"]))], run_dir / "long.mp4") if with_long else None
    shorts = [str(concat([vname(i, j == 0 and i in firsts) for j, i in enumerate(win)], run_dir / f"short_{k + 1}.mp4"))
              for k, win in enumerate(wins)]
    cover = draw_frame(backdrop(s["scenes"][0]["place"], pal, 1280, 720, .74), s["scenes"][0],
                       timeline(s["scenes"][0], tt[0][0]), [], durs[0] * .6, pal, s["characters"], 1280, 720, int(720 * .74), "")
    d = ImageDraw.Draw(cover)
    d.text((640, 120), s["title"][:44], font=_font(58), fill=pal[3], anchor="mm", stroke_width=4, stroke_fill="#000000")
    cover.save(run_dir / "cover.png")
    meta = {"long": str(long) if long else None, "long_sec": probe(long) if long else 0.0, "shorts": shorts,
            "short_sec": [probe(x) for x in shorts], "windows": wins, "settings": cfg, "hook": hook}
    if (long and meta["long_sec"] < 240) or len(shorts) < 3 or max(meta["short_sec"]) > 60:
        raise SystemExit(f"выпуск вне требований: {meta}")
    (run_dir / "render.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return meta


# ---------- idea (LLM) ----------

def sse_content(lines) -> str:
    """Склеить content из SSE-чанков chat.completions (reasoning_content игнор)."""
    out = []
    for ln in lines:
        ln = ln.decode() if isinstance(ln, bytes) else ln
        if not ln.startswith("data:") or ln[5:].strip() == "[DONE]":
            continue
        try:
            ch = json.loads(ln[5:])["choices"][0]["delta"].get("content")
        except (ValueError, KeyError, IndexError):
            continue
        out.append(ch or "")
    return "".join(out)


def router_stream(model: str, prompt: str, max_tokens: int, timeout: int = 600) -> str:
    """stream=True: длинный ответ не упирается в 100 с Cloudflare (HTTP 524 на non-stream, 19.10)."""
    import http.client
    import urllib.error
    import urllib.request
    from common import router_api_key, router_base_url
    req = urllib.request.Request(f"{router_base_url()}/chat/completions", method="POST", data=json.dumps({
        "model": model, "stream": True, "max_tokens": max_tokens, "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"Authorization": f"Bearer {router_api_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return sse_content(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"9router HTTP {e.code}: {e.read()[:300]!r}") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:  # обрыв SSE = IncompleteRead
        raise RuntimeError(f"9router network: {type(e).__name__}: {e}") from None


def idea(models=None) -> Path:
    from common import new_run_dir
    models = models or ["glm/glm-5.3-flash", "gemini/gemini-3.8-flash", "auto-worker-combo", "cx/gpt-5.5"]

    def ask(prompt, max_tokens):
        err = None
        for m in models:
            try:
                return parse_json(router_stream(m, prompt, max_tokens))
            except (RuntimeError, ValueError) as e:
                print(f"model {m}: {e}"[:300])
                err = e
        raise SystemExit(f"нет валидного ответа LLM: {err}")

    plan = next_plan()
    for attempt in range(3):
        s = ask(script_prompt(plan), 8000)
        try:
            s["scenes"] = [sc for sc in s.get("scenes", []) if isinstance(sc, dict) and sc.get("text")]
            validate_script(json.loads(json.dumps(s)))
            break
        except ValueError as e:
            print(f"script attempt {attempt + 1}: {e}")
    else:
        raise SystemExit("сценарий не прошёл валидацию 3 раза")
    chars = [{"id": c["id"], "label": c.get("label", c["id"])} for c in validate_script(json.loads(json.dumps(s)))["characters"]]

    def stage2(sc):
        try:
            sc.update({k: v for k, v in ask(scene_prompt(sc, chars), 3000).items() if k in ("cast", "actions")})
        except SystemExit as e:  # сцена без действий: персонаж просто стоит — не валим выпуск
            print(f"scene DSL skip: {e}")
        if not sc.get("cast"):
            sc["cast"] = [{"id": c["id"], "x": 0.3 + 0.4 * j, "mood": "calm"} for j, c in enumerate(chars[:2])]
        if len(sc.get("actions") or []) < 4:  # LLM не дал DSL: сцена не должна стоять статикой
            sc["actions"] = (sc.get("actions") or []) + auto_actions(sc["text"], sc["cast"])
            sc["auto"] = True
        return sc
    with ThreadPoolExecutor(6) as ex:
        s["scenes"] = list(ex.map(stage2, s["scenes"]))
    s = validate_script(s)
    s.update(channel="whatif", plan=plan, topic=plan["topic"])
    out = new_run_dir() / "idea.json"
    out.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"idea -> {out}: {s['title']} ({len(s['scenes'])} scenes, "
          f"{sum(len(sc['actions']) for sc in s['scenes'])} actions)")
    return out


# ---------- publish ----------

def descriptions(s: dict, long_url: str | None = None) -> tuple[str, str]:
    base = s.get("description", "").strip()
    long_d = "\n\n".join([base, AI_NOTE, HASHTAGS])
    short_d = "\n\n".join(p for p in [base, f"Full video: {long_url}" if long_url else "", AI_NOTE, "#Shorts " + HASHTAGS] if p)
    return long_d, short_d


def _playlist(y, title=PLAYLIST) -> str:
    items = y.playlists().list(part="snippet", mine=True, maxResults=50).execute().get("items", [])
    pid = next((i["id"] for i in items if i["snippet"]["title"] == title), None)
    return pid or y.playlists().insert(part="snippet,status", body={
        "snippet": {"title": title, "description": "Animated thought experiments drawn by code. " + AI_NOTE},
        "status": {"privacyStatus": "public"}}).execute()["id"]


def publish(run_dir: Path) -> dict:
    import importlib.util
    from googleapiclient.http import MediaFileUpload
    spec = importlib.util.spec_from_file_location("pub", Path(__file__).parent / "05_publish.py")
    pub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pub)
    s = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))
    meta = json.loads((run_dir / "render.json").read_text())
    done_f = run_dir / "published.json"
    done = json.loads(done_f.read_text()) if done_f.exists() else {}
    y = pub._get_youtube_service()
    pid = _playlist(y)

    def up(path, title, desc):
        body = {"snippet": {"title": title[:100], "description": desc, "tags": s.get("tags", [])[:15], "categoryId": "24",
                            "defaultLanguage": "en", "defaultAudioLanguage": "en"},
                "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}}
        req = y.videos().insert(part="snippet,status", body=body,
                                media_body=MediaFileUpload(str(path), mimetype="video/mp4", resumable=True, chunksize=4 << 20))
        vid = pub.upload_resumable(req)["id"]
        y.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": pid, "resourceId": {
            "kind": "youtube#video", "videoId": vid}}}).execute()
        return f"https://www.youtube.com/watch?v={vid}"
    long_d, _ = descriptions(s)
    if meta.get("long") and "long" not in done:  # long не каждый день (WHATIF_LONG_EVERY)  # идемпотентно: повтор шага не дублирует уже залитое
        done["long"] = up(meta["long"], s["title"], long_d)
        done_f.write_text(json.dumps(done, indent=2))
        try:
            y.thumbnails().set(videoId=done["long"].rsplit("=", 1)[1],
                               media_body=MediaFileUpload(str(run_dir / "cover.png"), mimetype="image/png")).execute()
        except Exception as e:
            print(f"thumbnail skip: {type(e).__name__}")
    _, short_d = descriptions(s, done.get("long"))  # ponytail: в день без long ссылки нет; ссылать на прошлый long, если понадобится
    for k, path in enumerate(meta["shorts"], 1):
        key = f"short_{k}"
        if key not in done:
            done[key] = up(path, f"{s['title'][:80]} (part {k}) #Shorts", short_d)
            done_f.write_text(json.dumps(done, indent=2))
    print(json.dumps(done, indent=2))
    return done


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("idea", "render", "publish"):
        sys.exit(__doc__)
    if not enabled():
        print(f"code-2D disabled (CODE2D!=1): {cmd} skipped")
        sys.exit(0)
    from common import latest_run_dir
    {"idea": lambda: idea(), "render": lambda: render(latest_run_dir()), "publish": lambda: publish(latest_run_dir())}[cmd]()
