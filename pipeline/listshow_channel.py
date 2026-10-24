#!/usr/bin/env python3
"""S1 ch2 long-form list-format («listshow»): 10-11 мин факт-лист в стиле топов Chill Dude Explains.

Флаг: LIST2D=1 (repo var). Выключен = все команды no-op с exit 0 (откат = снять флаг).
  python listshow_channel.py idea     -> runs/<new>/idea.json (LLM через 9router: 13-15 пунктов)
  python listshow_channel.py render   -> runs/<last>/long.mp4 (>=9 мин, 1920x1080) + short_1..3.mp4 + cover.png
  python listshow_channel.py publish  -> YouTube: long + 3 Shorts, runs/<last>/published.json
Визуальный язык общий с «What if» (whatif_channel.py: декорации, стикмен, караоке-сабы) — канальный бренд.
Анти-шаблон (inauthentic content): пункты с уникальными заголовками, места и голос TTS ротируются
между пунктами и выпусками; состояние .state/listshow_idx.txt коммитит CI.
Темы — свои формулировки по мотивам топ-30 by views канала-референса; текст пунктов всегда свой.
"""
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import whatif_channel as wf  # переиспользуем декорации/стикмена/тайминги/конкат: один визуальный язык канала

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".state"
FPS = wf.FPS
MIN_ITEMS, MAX_ITEMS = 12, 15
WORDS_PER_SEC = 2.8  # замер run 40050580825: 1444 слова = 518 с речи edge-tts rate +4% (2.5 давало план 584 с при факте 525 с)
ITEM_GAP_SEC = 0.45  # как в whatif: пауза между сценами
TARGET_MIN_SEC = 570.0  # 9.5 мин плана; published long проверяется >= 540
LONG_MIN_SEC = 540.0  # приёмка публикации: >= 9 мин
SHORT_LIMIT = wf.SHORT_LIMIT
PLAYLIST = "Fascinating Lists"
AI_NOTE = "AI-generated narration and code-drawn animation (synthetic content)."
HASHTAGS = "#facts #list #top10"
VOICES = ["en-US-GuyNeural", "en-US-AndrewNeural", "en-US-ChristopherNeural"]  # ротация голоса между пунктами
PLACES = wf.PLACES  # канальный набор декораций (общий с What if)
PALETTES = wf.PALETTES

TOPICS = [  # свои формулировки; источники идей - топ-30 референса by views (своя формулировка, не копия)
    "Things That Will Be Banned In Your Lifetime", "Facts Everyone Repeats That Are Simply Wrong",
    "Habits That Quietly Damage Your Body", "Places On Earth Where Humans Cannot Survive",
    "Skills You Can Learn Faster Than You Think", "Historical Events That Never Actually Happened",
    "Technicians' Tricks That Feel Like Cheating", "Everyday Things Designed To Fail On Purpose",
    "Instincts Your Body Keeps From Ancient Times", "Free Things That Are Worth More Than Money",
    "Experiments Scientists Refuse To Repeat", "Legends That Turned Out To Be True",
    "Sensations Everyone Feels But Never Talks About", "Rules You Break Daily Without Knowing",
    "Inventions Born From Complete Accidents",
]  # 15, взаимно просто с 4 ANGLES и 6 палитрами wf
ANGLES = [  # 4, взаимно просто с 15
    "count down from the last item to the first, saving the strangest for the end",
    "count up from 1, ending on the most useful one",
    "no numbers, walk by theme: body, history, money, nature",
    "open with the most shocking item, then descend into context",
]


def settings() -> dict:
    """Параметры выпуска из env (repo vars). LISTSHOW_LEGACY=1 - откат к поведениям по умолчанию."""
    try:
        shorts = max(3, min(6, int(os.environ.get("LISTSHOW_SHORTS", "3"))))
    except ValueError:
        shorts = 3
    try:
        target = max(540.0, float(os.environ.get("LISTSHOW_TARGET_SEC", str(TARGET_MIN_SEC))))
    except ValueError:
        target = TARGET_MIN_SEC
    return {"shorts": shorts, "target": target}


def enabled() -> bool:
    return os.environ.get("LIST2D", "").strip().lower() in ("1", "true", "yes", "on")


# ---------- план и сценарий ----------

def next_plan(state_dir: Path | None = None) -> dict:
    d = state_dir or STATE
    d.mkdir(parents=True, exist_ok=True)
    f = d / "listshow_idx.txt"
    i = int(f.read_text()) if f.exists() else 0
    f.write_text(str(i + 1))
    return {"topic": TOPICS[i % len(TOPICS)], "angle": ANGLES[i % len(ANGLES)],
            "palette": i % len(wf.PALETTES), "voice0": i % len(VOICES), "idx": i}


def script_prompt(plan: dict) -> str:
    return f"""You write narration for a faceless YouTube channel of list-style fact videos (10-11 minutes).
Video: "{plan['topic']}". Angle: {plan['angle']}.
Rules: total narration 1650-1850 words (about 10-11 minutes at a natural pace; under 1650 words is rejected), plain vivid US English,
second person where natural, grounded in real history/science/economics, no hype, no "like and subscribe".
Split into 13-15 list items, each 120-135 words of narration with its own short punchy item title (2-6 words).
Every item must stand alone: its own angle, its own example, no repeated filler phrasing between items.
Write everything in your own words; do not copy phrasing from other channels or websites.
Item 1 must hook in its first sentence. The final item lands a one-line takeaway.
Return STRICT JSON only (no markdown):
  title: list-style title matching the video, max 70 chars, must START with one of the words:
         Things, Facts, Habits, Places, Skills, Historical, Everyday, Instincts, Free, Experiments, Legends, Sensations, Rules, Inventions
  description: 2 sentences for YouTube
  tags: 6-10 English tags
  items: list of 13-15 objects {{"title": item title, "text": narration of the item,
         "place": one of {wf.PLACES}}}
"""


def parse_json(text: str) -> dict:
    return wf.parse_json(text)


def item_voice(plan_idx: int, k: int) -> str:
    return VOICES[(plan_idx + k) % len(VOICES)]


def planned_duration_sec(items: list) -> float:
    words = sum(len(str(i.get("text", "")).split()) for i in items)
    return words / WORDS_PER_SEC + ITEM_GAP_SEC * len(items)


def validate_script(s: dict) -> dict:
    """Доверенная нормализация вывода LLM: форма, хронометраж, анти-шаблонные проверки; рендер не падает."""
    title = str(s.get("title", "")).strip()
    if not re.match(r"^(Things|Facts|Habits|Places|Skills|Historical|Everyday|Instincts|Free|Experiments|Legends|Sensations|Rules|Inventions)\b", title, re.I):
        raise ValueError(f"title не списочный: {title!r}")
    s["title"] = title[:100]
    items = [i for i in (s.get("items") or []) if isinstance(i, dict)
             and str(i.get("title", "")).strip() and str(i.get("text", "")).strip()]
    if not MIN_ITEMS <= len(items) <= MAX_ITEMS:
        raise ValueError(f"пунктов {len(items)} вне {MIN_ITEMS}..{MAX_ITEMS}")
    seen = set()
    norm = []
    for k, it in enumerate(items):
        it["title"] = str(it["title"]).strip()[:80]
        key = re.sub(r"[^a-z0-9]", "", it["title"].lower())
        if key in seen:
            raise ValueError(f"повтор пункта: {it['title']!r}")
        seen.add(key)
        if it.get("place") not in wf.PLACES:
            it["place"] = wf.PLACES[sum(map(ord, it["title"])) % len(wf.PLACES)]
        norm.append(it)
    if len({i["place"] for i in norm}) < 3:
        raise ValueError("места не варьируются (<3): риск inauthentic-content")
    if planned_duration_sec(norm) < TARGET_MIN_SEC:
        raise ValueError(f"план {planned_duration_sec(norm):.0f} с < {TARGET_MIN_SEC:.0f} с: long < 9.5 мин")
    s["items"] = norm
    s["tags"] = [str(t) for t in (s.get("tags") or [])][:15]
    return s


CHARACTERS = [{"id": "you", "label": "You", "color": "#ffb000"},
              {"id": "buddy", "label": "Buddy", "color": "#4cc9f0"}]


def to_scene(it: dict, k: int, plan: dict) -> dict:
    """Пункт -> сцена whatif-DSL: детерминированная keyword-анимация (actions по словам реплики).
    Нормализация полей сцены повторяет зажимы wf.validate_script, но для одиночной сцены."""
    cast = [{"id": "you", "x": 0.3 + 0.4 * ((k + plan.get("idx", 0)) % 2), "mood": "calm"}]
    if k % 3 == 1:  # визуальная вариация внутри выпуска: часть пунктов с двумя персонажами
        cast.append({"id": "buddy", "x": 0.75, "mood": "happy"})
    sc = {"place": it["place"], "text": it["text"], "cast": cast,
          "actions": wf.auto_actions(it["text"], cast)}
    ids = {c["id"] for c in CHARACTERS}
    sc["cast"] = [{"id": c["id"], "x": wf._f(c.get("x"), 0.1, 0.9, 0.5),
                   "mood": c.get("mood") if c.get("mood") in wf.MOODS else "calm"}
                  for c in sc["cast"] if c["id"] in ids][:3]
    acts = []
    for a in sc["actions"]:
        if a.get("do") in wf.ACTIONS and (a["do"] not in wf.NEEDS_WHO or a.get("who") in ids):
            if a["do"] == "spawn" and a.get("prop") not in wf.PROPS:
                continue
            if a["do"] == "mood" and a.get("mood") not in wf.MOODS:
                a["mood"] = "shocked"
            a["say_text"] = str(a.pop("text", ""))[:28]
            acts.append(a)
    sc["actions"] = sorted(acts, key=lambda a: a["word"])
    return sc


# ---------- idea ----------

def idea(models=None) -> Path:
    from common import new_run_dir
    models = models or ["glm/glm-5.3-flash", "gemini/gemini-3.8-flash", "auto-worker-combo"]
    plan = next_plan()
    prompt = script_prompt(plan)
    s = None
    err = None
    for round_ in range(3):  # роутер/модели бывают недоступны короткими окнами: 3 круга по списку
        for m in models:  # битый JSON, обрыв SSE и короткий план - одна и та же попытка: следующая модель
            try:
                s = validate_script(parse_json(wf.router_stream(m, prompt, 12000)))
                break
            except Exception as e:  # router: HTTP/525/429, IncompleteRead, битый JSON, ValueError валидации
                print(f"model {m}: {type(e).__name__}: {e}"[:300])
                err = e
                s = None
        if s is not None:
            break
    if s is None:
        raise SystemExit(f"нет валидного сценария за 3 круга: {err}")
    s.update(channel="listshow", plan=plan, topic=plan["topic"])
    out = new_run_dir() / "idea.json"
    out.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"idea -> {out}: {s['title']} ({len(s['items'])} items, plan {planned_duration_sec(s['items']):.0f}s)")
    return out


# ---------- render ----------

def tts(text: str, voice: str, out: Path) -> tuple[list, float]:
    """edge-tts (бесплатно) с пословными границами; voice варьируется между пунктами."""
    import asyncio
    import edge_tts

    async def go():
        bounds = []
        c = edge_tts.Communicate(text, voice, rate="+4%", boundary="WordBoundary")
        with open(out, "wb") as f:
            async for ch in c.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    s0 = ch["offset"] / 1e7
                    bounds.append((s0, s0 + ch["duration"] / 1e7, ch["text"]))
        return bounds
    for attempt in range(3):
        try:
            bounds = asyncio.run(go())
            break
        except Exception as e:  # сетевой сбой edge-tts (повтор как в whatif #141)
            print(f"tts retry {attempt + 1}: {type(e).__name__}")
            if attempt == 2:
                raise
    return bounds, wf.probe(out)


def render_workers(jobs: int) -> int:
    return wf.render_workers(jobs)


def render_item(sc, bounds, audio, dur, pal, characters, out, W, H, banner="", hook=""):
    return wf.render_scene(sc, bounds, audio, dur, pal, characters, out, W, H, banner=banner, hook=hook)


def _render_job(args):
    return str(render_item(*args))


def short_windows(durs: list, n: int = 3, limit: float = SHORT_LIMIT, floor: float = 20.0) -> list:
    return wf.short_windows(durs, n=n, limit=limit, floor=floor)


def concat(parts: list, out: Path) -> Path:
    return wf.concat(parts, out)


def draw_cover(s: dict, pal, out: Path) -> Path:
    """Обложка: крупный текст заголовка (3-5 слов) + стикмен на декорации первого пункта."""
    sc = to_scene(s["items"][0], 0, s.get("plan", {}))
    chars = [{"id": c["id"], "label": c["label"], "color": c["color"]} for c in _cover_chars()]
    im = wf.draw_frame(wf.backdrop(sc["place"], pal, 1280, 720, .74), sc, wf.timeline(sc, []), [], 0.0,
                       pal, chars, 1280, 720, int(720 * .74), "")
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    words = re.sub(r"[^A-Za-z0-9 ]", "", s["title"]).split()
    big = " ".join(words[:5])
    f = wf._font(96)
    while d.textlength(big, font=f) > 1280 * .88 and f.size > 40:
        f = wf._font(f.size - 6)
    tw = d.textlength(big, font=f)
    y = 130
    d.text((640 + 4, y + 4), big, font=f, fill="#000000", anchor="mm", stroke_width=6, stroke_fill="#000000")
    d.text((640, y), big, font=f, fill=pal[3], anchor="mm", stroke_width=2, stroke_fill="#000000")
    f2 = wf._font(44)
    sub = " ".join(words[5:11])
    if sub:
        d.text((640, y + 110), sub, font=f2, fill=pal[2], anchor="mm", stroke_width=3, stroke_fill="#000000")
    im.save(out)
    return out


def _cover_chars():
    return [{"id": "you", "label": "You", "color": "#ffb000", "x": 0.5, "mood": "shocked"}]


def render(run_dir: Path) -> dict:
    s = validate_script(json.loads((run_dir / "idea.json").read_text(encoding="utf-8")))
    cfg = settings()
    plan = s.get("plan", {})
    pal = wf.PALETTES[plan.get("palette", 0) % len(wf.PALETTES)]
    chars = CHARACTERS
    w = run_dir / "listshow"
    w.mkdir(exist_ok=True)
    scenes = [to_scene(it, k, plan) for k, it in enumerate(s["items"])]
    with ThreadPoolExecutor(6) as ex:  # TTS - сеть, параллельно
        tt = list(ex.map(lambda k: tts(s["items"][k]["text"], item_voice(plan.get("idx", 0), k),
                                       w / f"{k:02d}.mp3"), range(len(s["items"]))))
    durs = [d + ITEM_GAP_SEC for _, d in tt]
    (w / "timing.json").write_text(json.dumps([{"dur": d, "voice": item_voice(plan.get("idx", 0), k),
                                                "bounds": b} for k, ((b, _), d) in enumerate(zip(tt, durs))]))
    wins = short_windows(durs, n=cfg["shorts"], limit=cfg_short_limit(cfg))
    hook = s["title"]
    firsts = {win[0] for win in wins}
    vname = lambda k, h: w / f"V{k:02d}{'h' if h else ''}.mp4"  # noqa: E731
    jobs = [(scenes[k], tt[k][0], w / f"{k:02d}.mp3", durs[k], pal, chars, w / f"L{k:02d}.mp4", 1920, 1080,
             s["items"][k]["title"], hook if k == 0 else "") for k in range(len(scenes))]
    vert = sorted({(k, k in firsts and j == 0) for win in wins for j, k in enumerate(win)})
    jobs += [(scenes[k], tt[k][0], w / f"{k:02d}.mp3", durs[k], pal, chars, vname(k, h), 1080, 1920,
              s["title"], hook if h else "") for k, h in vert]
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(render_workers(len(jobs))) as ex:
        list(ex.map(_render_job, jobs))
    long = concat([w / f"L{k:02d}.mp4" for k in range(len(scenes))], run_dir / "long.mp4")
    shorts = [str(concat([vname(k, j == 0 and k in firsts) for j, k in enumerate(win)], run_dir / f"short_{n + 1}.mp4"))
              for n, win in enumerate(wins)]
    cover = draw_cover(s, pal, run_dir / "cover.png")
    meta = {"long": str(long), "long_sec": wf.probe(long), "shorts": shorts,
            "short_sec": [wf.probe(x) for x in shorts], "windows": wins, "settings": cfg, "plan": plan}
    if meta["long_sec"] < LONG_MIN_SEC or len(shorts) < 3 or max(meta["short_sec"]) > 60:
        raise SystemExit(f"выпуск вне требований: {meta}")
    (run_dir / "render.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return meta


def cfg_short_limit(cfg: dict) -> float:
    return SHORT_LIMIT


# ---------- publish ----------

def descriptions(s: dict, long_url: str | None = None) -> tuple[str, str]:
    base = str(s.get("description", "")).strip()
    long_d = "\n\n".join(p for p in [base, AI_NOTE, HASHTAGS] if p)
    short_d = "\n\n".join(p for p in [base, f"Full video: {long_url}" if long_url else "", AI_NOTE,
                                        "#Shorts " + HASHTAGS] if p)
    return long_d, short_d


def _playlist(y) -> str:
    items = y.playlists().list(part="snippet", mine=True, maxResults=50).execute().get("items", [])
    pid = next((i["id"] for i in items if i["snippet"]["title"] == PLAYLIST), None)
    return pid or y.playlists().insert(part="snippet,status", body={
        "snippet": {"title": PLAYLIST, "description": "Fact lists drawn by code. " + AI_NOTE},
        "status": {"privacyStatus": "public"}}).execute()["id"]


def upload_limit_hit(e: Exception) -> bool:
    """Суточный лимит загрузок YouTube (400 uploadLimitExceeded): не ошибка выпуска long."""
    return "uploadLimitExceeded" in str(e)


def privacy() -> str:
    """CH2_PRIVACY=private|unlisted = сухой прогон launch-гейта (t_f807dc99); иначе public."""
    v = os.environ.get("CH2_PRIVACY", "public")
    assert v in ("public", "private", "unlisted"), v
    return v


def verify(run_dir: Path, y=None, probe=None) -> list:
    """Автосверка выложенного: title = idea.json, privacy = privacy(), ролик в плейлисте, длина = файл ±2 с,
    у Shorts в описании ссылка на long. Возвращает список расхождений (пусто = зелёно)."""
    import re
    s = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))
    meta = json.loads((run_dir / "render.json").read_text())
    done = json.loads((run_dir / "published.json").read_text())
    if y is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pub", Path(__file__).parent / "05_publish.py")
        pub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pub)
        y = pub._get_youtube_service()
    probe = probe or (lambda f: float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
        capture_output=True, text=True, check=True).stdout))
    want = {"long": (meta["long"], s["title"][:100])}
    for k, path in enumerate(meta["shorts"], 1):
        want[f"short_{k}"] = (path, f"{s['title'][:80]} (part {k}) #Shorts"[:100])
    pid = _playlist(y)
    in_pl = {i["snippet"]["resourceId"]["videoId"] for i in
             y.playlistItems().list(part="snippet", playlistId=pid, maxResults=50).execute().get("items", [])}
    bad = []
    for key, url in done.items():
        vid = url.rsplit("=", 1)[1]
        it = (y.videos().list(part="snippet,status,contentDetails", id=vid).execute().get("items") or [None])[0]
        if not it:
            bad.append(f"{key}: видео {vid} не найдено")
            continue
        path, title = want[key]
        m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", it["contentDetails"]["duration"])
        dur = sum(int(g or 0) * k for g, k in zip(m.groups(), (3600, 60, 1))) if m else -1
        checks = {"title": (it["snippet"]["title"], title), "privacy": (it["status"]["privacyStatus"], privacy()),
                  "playlist": (vid in in_pl, True)}
        for name, (got, exp) in checks.items():
            if got != exp:
                bad.append(f"{key}: {name} {got!r} != {exp!r}")
        if abs(dur - probe(path)) > 2:
            bad.append(f"{key}: длина {dur} с != файл {probe(path):.0f} с")
        if key.startswith("short_") and "long" in done and done["long"] not in it["snippet"]["description"]:
            bad.append(f"{key}: нет ссылки на long в описании")
        print(f"verify {key} {vid}: title/privacy/playlist/длина {dur} с")
    print("VERIFY:", "OK" if not bad else bad)
    return bad


def publish(run_dir: Path) -> dict:
    import importlib.util
    from googleapiclient.http import MediaFileUpload
    spec = importlib.util.spec_from_file_location("pub", Path(__file__).parent / "05_publish.py")
    pub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pub)
    s = validate_script(json.loads((run_dir / "idea.json").read_text(encoding="utf-8")))
    meta = json.loads((run_dir / "render.json").read_text())
    done_f = run_dir / "published.json"
    done = json.loads(done_f.read_text()) if done_f.exists() else {}
    y = pub._get_youtube_service()
    pid = _playlist(y)

    def up(path, title, desc):
        body = {"snippet": {"title": title[:100], "description": desc, "tags": s.get("tags", [])[:15],
                            "categoryId": "24", "defaultLanguage": "en", "defaultAudioLanguage": "en"},
                "status": {"privacyStatus": privacy(), "selfDeclaredMadeForKids": False,
                           "containsSyntheticMedia": True}}
        req = y.videos().insert(part="snippet,status", body=body,
                                media_body=MediaFileUpload(str(path), mimetype="video/mp4",
                                                           resumable=True, chunksize=4 << 20))
        vid = pub.upload_resumable(req)["id"]
        y.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": pid, "resourceId": {
            "kind": "youtube#video", "videoId": vid}}}).execute()
        return f"https://www.youtube.com/watch?v={vid}"

    long_d, _ = descriptions(s)
    if "long" not in done:  # long каждый день (это и есть формат); идемпотентно по published.json
        done["long"] = up(meta["long"], s["title"], long_d)
        done_f.write_text(json.dumps(done, indent=2))
        try:
            y.thumbnails().set(videoId=done["long"].rsplit("=", 1)[1],
                               media_body=MediaFileUpload(str(run_dir / "cover.png"),
                                                          mimetype="image/png")).execute()
        except Exception as e:
            print(f"thumbnail skip: {type(e).__name__}")
    _, short_d = descriptions(s, done.get("long"))
    for k, path in enumerate(meta["shorts"], 1):
        key = f"short_{k}"
        if key not in done:
            try:
                done[key] = up(path, f"{s['title'][:80]} (part {k}) #Shorts", short_d)
            except Exception as e:
                if not upload_limit_hit(e):
                    raise
                # ponytail: суточный лимит загрузок канала; long уже вышел, Shorts пропускаем до завтра
                print(f"shorts stop: uploadLimitExceeded after {k - 1} shorts")
                break
            done_f.write_text(json.dumps(done, indent=2))
    print(json.dumps(done, indent=2))
    return done


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("idea", "render", "publish", "verify"):
        sys.exit(__doc__)
    if not enabled():
        print(f"listshow disabled (LIST2D!=1): {cmd} skipped")
        sys.exit(0)
    from common import latest_run_dir
    {"idea": lambda: idea(), "render": lambda: render(latest_run_dir()),
     "publish": lambda: publish(latest_run_dir()),
     "verify": lambda: sys.exit(1 if verify(latest_run_dir()) else 0)}[cmd]()
