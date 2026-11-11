#!/usr/bin/env python3
"""Шаг 2: сгенерировать обложку (PNG) по cover_prompt из idea.json через 9router image API.

t_629a7ba2: 27-28.10 codex/gpt-image-1.5 отдавал 429 «usage limit (reset after 6-32s)» -> градиент-заглушка ->
04b FAIL (V14). Цепочка: модель -> ретрай по «reset after Ns» -> следующая модель -> банк готовых артов
(assets/cover_bank/<lofi|phonk>/) -> заглушка только при пустом банке. Путь пишется в cover_source.json (04b печатает).
"""
import base64
import hashlib
import io
import json
import os
import re
import time
from pathlib import Path

from common import router_post, latest_run_dir

# (модель, размеры по порядку). flux-1-schnell (Cloudflare) не принимает size вовсе -> None.
SIZE = "1536x1024"  # горизонталь под 16:9; квадрат 04 обрежет. Эталон формата (используют тесты).
# gpt-image-1.5 (cx) invalidated oauth at 9router; flux-1-schnell (cf) daily free limit exhausted.
# Replacement: nvidia/flux_2-klein-4b (primary), openrouter/gemini-2.5-flash-image (fallback)
_DEFAULT_MODELS = [
    ("nvidia:flux_2-klein-4b", [None]),
    ("openrouter:gemini-2.5-flash-image", [SIZE, "1024x1024"]),
]
MODELS = json.loads(os.environ.get("ACF_COVER_MODELS", "[]")) or _DEFAULT_MODELS
# ponytail: 401/403/404/400 — без права/модель не найдена/плохой запрос, ретраи только жгут лимиты; 408/5xx/429 — временно/перезагрузка
_AUTH_FAIL = ("HTTP 401", "HTTP 403", "HTTP 404", "HTTP 400", "HTTP 408")
RETRY_MAX_WAIT = 60  # ждём «reset after Ns» только если окно короткое; дольше -> следующая модель
BANK_DIR = Path(__file__).resolve().parent.parent / "assets" / "cover_bank"
# единый узнаваемый стиль канала: меняется только сцена из idea.json.
# Phonk-выпуск (t_c678b8fa шаг 3) — свой стиль: ночная дорога/неон вместо
# тёплой аниме-комнаты; концепт берётся из cover_prompt (LLM уже знает жанр).
STYLE = ("cozy anime lofi illustration, 90s anime cel shading, soft film grain, "
         "warm muted pastel palette, gentle lamp light, wide 16:9 composition, "
         "scene fills the whole frame, no text, no letters, no watermark")
STYLE_PHONK = ("moody night drive phonk illustration, neon city glow, wet asphalt reflections, "
               "cinematic haze, dark muted palette with magenta and cyan accents, "
               "wide 16:9 composition, scene fills the whole frame, no text, no letters, no watermark")


def _genre() -> str:
    # жанр по env GENRE (ставит workflow matrix); cover_prompt может не содержать слова жанра.
    return "phonk" if "phonk" in (os.environ.get("GENRE") or "").lower() else "lofi"


def styled(prompt: str) -> str:
    style = STYLE_PHONK if _genre() == "phonk" else STYLE
    return f"{prompt.rstrip(' ,.')}. Style: {style}"


def fallback_cover(prompt: str, out_path) -> None:
    """Последний рубеж (банк пуст) -> вертикальный градиент (цвета из хэша промпта); 04b такой выпуск валит (V14)."""
    from PIL import Image

    h = hashlib.sha256(prompt.encode()).digest()
    top, bot = h[:3], h[3:6]
    top = tuple(40 + c % 120 for c in top)   # приглушённые пастельно-ночные тона
    bot = tuple(10 + c % 60 for c in bot)
    img = Image.new("RGB", (1024, 1024))
    px = img.load()
    for y in range(1024):
        t = y / 1023
        row = tuple(int(a + (b - a) * t) for a, b in zip(top, bot))
        for x in range(1024):
            px[x, y] = row
    img.save(out_path)


def _save_png(raw: bytes, out_path) -> None:
    """flux отдаёт JPEG, gpt-image PNG; дальше (04, thumbnails.set image/png) нужен PNG."""
    from PIL import Image
    Image.open(io.BytesIO(raw)).convert("RGB").save(out_path, "PNG")


def generate(prompt: str, out_path, log: list):
    """Модели по очереди; 429 с коротким «reset after Ns» = один повтор после паузы. Вернёт модель или None."""
    for model, sizes in MODELS:
        for size in sizes:
            body = {"model": model, "prompt": prompt, "n": 1, **({"size": size} if size else {})}
            for attempt in (1, 2):
                try:
                    resp = router_post("/images/generations", body, timeout=180)
                    _save_png(base64.b64decode(resp["data"][0]["b64_json"]), out_path)
                    log.append({"model": model, "size": size, "attempt": attempt, "ok": True})
                    return model
                except Exception as e:  # сеть/HTTP/битый ответ/не картинка — всё = эта попытка не удалась
                    err = str(e)[:200]
                    log.append({"model": model, "size": size, "attempt": attempt, "error": err})
                    print(f"cover {model} {size or 'default'} #{attempt}: {err}")
                    # Не тратим лимиты на 401/403/404/408 для конкретной модели — переключаемся дальше по цепочке.
                    if any(marker in err for marker in _AUTH_FAIL):
                        break
                    m = re.search(r"reset after (?:(\d+)m )?(\d+)s", err) if "429" in err else None
                    wait = (int(m.group(1) or 0) * 60 + int(m.group(2)) + 2) if m else None
                    if attempt == 1 and wait is not None and wait <= RETRY_MAX_WAIT:
                        print(f"cover: 429, ретрай через {wait} с")
                        time.sleep(wait)
                        continue
                    break
            if any(marker in log[-1].get("error", "") for marker in _AUTH_FAIL):
                continue  # следующая модель, не застреваем на 401/403/404/408
            if "429" in log[-1].get("error", ""):
                break  # лимит модели: другой размер не поможет -> следующая модель
    return None


def bank_pick(prompt: str, bank_dir: Path):
    """Готовый арт жанра; выбор по хэшу промпта (разные идеи -> разные арты).
    ponytail: хэш без ротации, повторы возможны; апгрейд — ротация через .state, если банк станет частым путём."""
    files = sorted(p for p in (bank_dir / _genre()).glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    if not files:
        return None
    return files[int(hashlib.sha256(prompt.encode()).hexdigest(), 16) % len(files)]


def main() -> None:
    run_dir = latest_run_dir()
    idea = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))
    out_path = run_dir / "cover.png"
    bank_dir = Path(os.environ.get("ACF_COVER_BANK") or BANK_DIR)
    log: list = []

    model = generate(styled(idea["cover_prompt"]), out_path, log)
    art = None if model else bank_pick(idea["cover_prompt"], bank_dir)
    if model:
        path = "api" if len(log) == 1 else ("retry" if model == MODELS[0][0] else "fallback_model")
        src = {"path": path, "model": model}
    elif art:
        _save_png(art.read_bytes(), out_path)
        src = {"path": "bank", "file": art.name}
    else:
        print("image API недоступен, банк артов пуст; фолбэк-обложка")
        fallback_cover(idea["cover_prompt"], out_path)
        src = {"path": "placeholder"}
        # V14: маркер для 04b — заглушка без арта не публикуется
        reason = log[-1].get("error", "?") if log else "?"
        (run_dir / "cover_fallback.json").write_text(json.dumps({"reason": reason[:300]}, ensure_ascii=False), encoding="utf-8")
    (run_dir / "cover_source.json").write_text(json.dumps({**src, "attempts": log}, ensure_ascii=False), encoding="utf-8")
    print(f"cover_source: {src['path']} {src.get('model') or src.get('file') or ''}")
    print(f"cover -> {out_path}")


if __name__ == "__main__":
    main()
