#!/usr/bin/env python3
"""Шаг 2: сгенерировать обложку (PNG) по cover_prompt из idea.json через 9router image API."""
import base64
import hashlib
import json

from common import router_post, latest_run_dir

MODEL = "cx/gpt-image-1.5"
SIZE = "1536x1024"  # горизонталь под кадр 16:9 (квадрат давал чёрные поля)
# единый узнаваемый стиль канала: меняется только сцена из idea.json.
# Phonk-выпуск (t_c678b8fa шаг 3) — свой стиль: ночная дорога/неон вместо
# тёплой аниме-комнаты; концепт берётся из cover_prompt (LLM уже знает жанр).
STYLE = ("cozy anime lofi illustration, 90s anime cel shading, soft film grain, "
         "warm muted pastel palette, gentle lamp light, wide 16:9 composition, "
         "scene fills the whole frame, no text, no letters, no watermark")
STYLE_PHONK = ("moody night drive phonk illustration, neon city glow, wet asphalt reflections, "
               "cinematic haze, dark muted palette with magenta and cyan accents, "
               "wide 16:9 composition, scene fills the whole frame, no text, no letters, no watermark")


def styled(prompt: str) -> str:
    # жанр определяем по env GENRE (ставит workflow matrix); cover_prompt может
    # не содержать слова жанра (фолбэк-сцены аниме-специфичны).
    import os
    genre = (os.environ.get("GENRE") or "").lower()
    style = STYLE_PHONK if "phonk" in genre else STYLE
    return f"{prompt.rstrip(' ,.')}. Style: {style}"


def fallback_cover(prompt: str, out_path) -> None:
    """Image API недоступен -> вертикальный градиент (цвета из хэша промпта).
    ponytail: аварийная обложка без арта; апгрейд — пул одобренных обложек в репо."""
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


def main() -> None:
    run_dir = latest_run_dir()
    idea = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))

    out_path = run_dir / "cover.png"
    try:
        body = {"model": MODEL, "prompt": styled(idea["cover_prompt"]), "size": SIZE, "n": 1}
        try:
            resp = router_post("/images/generations", body, timeout=180)
        except RuntimeError as e:  # модель не умеет 1536x1024 -> квадрат, 04 обрежет до 16:9
            print(f"size {SIZE} отклонён ({str(e)[:120]}); 1024x1024")
            resp = router_post("/images/generations", {**body, "size": "1024x1024"}, timeout=180)
        out_path.write_bytes(base64.b64decode(resp["data"][0]["b64_json"]))
    except (RuntimeError, KeyError, IndexError, ValueError) as e:
        print(f"image API недоступен ({e}); фолбэк-обложка"[:300])
        fallback_cover(idea["cover_prompt"], out_path)
        # V14: маркер для 04b — заглушка без арта не публикуется
        (run_dir / "cover_fallback.json").write_text(json.dumps({"reason": str(e)[:300]}, ensure_ascii=False), encoding="utf-8")
    print(f"cover -> {out_path}")


if __name__ == "__main__":
    main()
