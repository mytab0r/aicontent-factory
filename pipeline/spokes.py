#!/usr/bin/env python3
"""Hub-and-spoke (t_705386b0): один idea.json (хаб = скрипт Short) -> тексты/картинка для 5 площадок.

  python spokes.py [run_dir]   -> <run>/spokes/{spokes.json,pin.png,x.txt,tg.txt,blog.md}

Роли: Short = охват, Pinterest = поиск (вечнозелёный, ведёт в блог), X = охват/обсуждение,
блог = поиск (SEO) + конверсия, TG-канал = удержание + конверсия. CTA и метка источника у каждой своя:
воронка-бот: ?start=<площадка>_<ниша> (бот пишет start-аргумент в users.src); прочее: UTM.
Публикация отдельными шагами (API/кредиты площадок, отчёт t_705386b0); этот модуль только готовит.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

BOT = "https://t.me/Tar0_Astral_bot"
BLOG_BASE = "https://mytab0r.github.io/s1-blog/"  # ponytail: GitHub Pages ($0); свой домен — когда блог даст трафик
PLATFORMS = {"yt": "youtube", "pin": "pinterest", "x": "x", "blog": "blog", "tg": "telegram"}
BOT_NICHES = {"tarot", "manifest", "love", "astro"}  # ниши с таро-воронкой; прочие каналы — UTM на свой сайт
BOT_CTA, BOT_DISCLAIMER = "Free AI tarot reading in Telegram (for entertainment)", "For entertainment only."
SITE_CTA = "Full breakdown with numbers"


def cta(niche: str) -> tuple:
    """(текст CTA, дисклеймер) по нише: таро-бот только для ниш с ботом."""
    return (BOT_CTA, BOT_DISCLAIMER) if niche in BOT_NICHES else (SITE_CTA, "")


def funnel_url(niche: str, platform: str) -> str:
    assert platform in PLATFORMS, platform
    if niche in BOT_NICHES:
        return f"{BOT}?start={platform}_{niche}"  # yt_tarot = уже розданные ссылки t_255c099a
    return BLOG_BASE + "?" + urlencode({"utm_source": PLATFORMS[platform], "utm_medium": "social", "utm_campaign": niche})


def source_platform(start: str) -> str:
    """users.src бота -> ключ площадки (yt/pin/x/blog/tg) или 'other' (каталоги, direct)."""
    p = (start or "").split("_", 1)[0]
    return p if "_" in (start or "") and p in PLATFORMS else "other"


# Запрос к БД бота (/data/bot.db): переходы (уникальные /start) и плательщики по users.src за окно.
SOURCE_SQL = """SELECT u.src,
  COUNT(DISTINCT CASE WHEN e.kind='start' THEN e.uid END),
  COUNT(DISTINCT CASE WHEN e.kind='payment' THEN e.uid END)
FROM events e JOIN users u ON u.id=e.uid WHERE e.ts>=? GROUP BY u.src"""
KILL_SHARE_PCT, KILL_DAYS = 1.0, 14  # правило KILL: площадка с вкладом <1% переходов за 14 дней отключается


def by_platform(rows) -> dict:
    """rows (src, starts, payers) -> {площадка: starts, payers, cr_pct, share_pct}."""
    agg = {p: [0, 0] for p in [*PLATFORMS, "other"]}
    for src, st, pay in rows:
        a = agg[source_platform(src)]
        a[0] += st
        a[1] += pay
    total = sum(a[0] for a in agg.values())
    return {p: {"starts": s, "payers": y, "cr_pct": round(100 * y / s, 2) if s else 0.0,
                "share_pct": round(100 * s / total, 1) if total else 0.0} for p, (s, y) in agg.items()}


def kill_list(agg: dict) -> list:
    if not sum(v["starts"] for v in agg.values()):
        return []  # нет трафика = нет знаменателя, решения нет
    return sorted(p for p in PLATFORMS if agg[p]["share_pct"] < KILL_SHARE_PCT)


STATS_FIELDS = ["date", "window_days", "platform", "starts", "payers", "cr_pct", "share_pct", "kill"]


def append_stats(path: Path, rows, date: str) -> dict:
    """Дописать в stats_sources.csv срез за KILL_DAYS по каждой площадке (+other)."""
    import csv
    agg, kill = by_platform(rows), set(kill_list(by_platform(rows)))
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, STATS_FIELDS)
        if new:
            w.writeheader()
        for p, v in agg.items():
            w.writerow({"date": date, "window_days": KILL_DAYS, "platform": p, **v, "kill": int(p in kill)})
    return agg


def _blog_url(slug: str, platform: str) -> str:
    return f"{BLOG_BASE}{slug}/?" + urlencode({"utm_source": PLATFORMS[platform], "utm_medium": "social",
                                                "utm_campaign": "s1"})


def _cut(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def build_spokes(idea: dict, niche: str, slug: str) -> dict:
    title, beats = idea["title"], idea["beats"]
    says = [b["say"] for b in beats]
    hook = idea.get("hook")
    if not hook:  # нет отдельного хука: хуком становится первый бит, из списка его убираем
        hook, says = says[0], says[1:]
    CTA, DISCLAIMER = cta(niche)
    tags = " ".join("#" + t.replace(" ", "") for t in idea.get("tags", [])[:4])
    # X: хук -> пункты -> CTA со ссылкой только в последнем твите (ссылка в первом режет охват)
    thread = [_cut(f"{hook} 🧵", 280)] + [_cut(f"{i}/ {s}", 280) for i, s in enumerate(says, 1)]
    thread.append(_cut(f"{CTA}: {funnel_url(niche, 'x')}", 280))
    tg = _cut("\n\n".join([f"<b>{title}</b>", hook, *[f"• {s}" for s in says[:4]],
                           f'<a href="{funnel_url(niche, "tg")}">{CTA}</a>', DISCLAIMER]).strip(), 1024)
    meta = _cut(f"{hook} {idea.get('description', '')}".strip(), 160)
    if len(meta) < 50:
        meta = _cut(f"{meta} {' '.join(says)}", 160)
    body = "\n\n".join(f"## {b.get('label', '').title() or 'Step'}\n\n{b['say']}" for b in beats)
    blog = (f'---\ntitle: "{title}"\ndescription: "{meta}"\nslug: {slug}\ntags: {json.dumps(idea.get("tags", []))}\n---\n\n'
            f"# {title}\n\n{hook}\n\n{body}\n\n---\n\n**[{CTA}]({funnel_url(niche, 'blog')})**\n"
            + (f"\n*{DISCLAIMER}*\n" if DISCLAIMER else ""))
    return {
        "short": {"role": "охват", "pinned_comment": f"{CTA}: {funnel_url(niche, 'yt')}"},
        "pinterest": {"role": "поиск", "title": _cut(title, 100),
                      "description": _cut(f"{hook} {' '.join(says[:3])} {tags}", 500),
                      "link": _blog_url(slug, "pin")},
        "x": {"role": "охват", "thread": thread},
        "blog": {"role": "поиск+конверсия", "slug": slug, "markdown": blog},
        "tg": {"role": "удержание+конверсия", "text": tg, "parse_mode": "HTML"},
    }


def pin_image(idea: dict, path: Path, bg="#1b1030", acc="#f2c94c", fg="#ffffff") -> Path:
    """Инфографика 1000x1500 (2:3, рекомендованный формат Pinterest): заголовок + цифры битов.
    Высота блоков и кегль цифры подгоняются под место, футер зарезервирован (не налезает)."""
    from PIL import Image, ImageDraw
    from owning_channel import _font, _wrap
    W, H, M, FOOT, GAP = 1000, 1500, 60, 110, 22
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    y = 70
    for ln in _wrap(d, idea["title"], _font(60), W - 2 * M)[:4]:
        d.text((W / 2, y + 36), ln, font=_font(60), fill=fg, anchor="mm")
        y += 76
    beats = idea["beats"][:5]
    y += 30
    bh = min(220, (H - FOOT - y) // len(beats) - GAP)
    col, body_w = 250, W - 2 * M - 250 - 30
    for b in beats:
        d.rounded_rectangle([M, y, W - M, y + bh], radius=24, outline=acc, width=5)
        big, fs = b["big"][:7], 76
        while fs > 30 and d.textlength(big, font=_font(fs)) > col - 40:
            fs -= 4
        d.text((M + col / 2, y + bh / 2), big, font=_font(fs), fill=acc, anchor="mm")
        lines = _wrap(d, b["say"], _font(30, bold=False), body_w)[: max(1, (bh - 24) // 38)]
        yy = y + bh / 2 - (len(lines) - 1) * 19
        for ln in lines:
            d.text((M + col + 10, yy), ln, font=_font(30, bold=False), fill=fg, anchor="lm")
            yy += 38
        y += bh + GAP
    d.text((W / 2, H - FOOT / 2), "Read more ↗", font=_font(40), fill=acc, anchor="mm")
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def write_all(run_dir: Path) -> Path:
    idea = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))
    niche = idea.get("niche") or idea.get("channel") or "tarot"
    slug = "-".join("".join(c if c.isalnum() else " " for c in idea["title"].lower()).split())[:60]
    s = build_spokes(idea, niche, slug)
    out = run_dir / "spokes"
    out.mkdir(exist_ok=True)
    pin_image(idea, out / "pin.png")
    (out / "spokes.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "x.txt").write_text("\n\n---\n\n".join(s["x"]["thread"]), encoding="utf-8")
    (out / "tg.txt").write_text(s["tg"]["text"], encoding="utf-8")
    (out / "blog.md").write_text(s["blog"]["markdown"], encoding="utf-8")
    print(f"spokes -> {out}")
    return out


if __name__ == "__main__":
    if sys.argv[1:2] == ["stats"]:  # stdin = JSON [[src, starts, payers], ...] из SOURCE_SQL; argv[2] = csv
        import datetime as dt
        print(json.dumps(append_stats(Path(sys.argv[2]), json.load(sys.stdin), dt.date.today().isoformat())))
    elif len(sys.argv) > 1:
        write_all(Path(sys.argv[1]))
    else:
        from common import latest_run_dir
        write_all(latest_run_dir())
