#!/usr/bin/env python3
"""Шаг 2: сгенерировать обложку (PNG) по cover_prompt из idea.json через 9router image API."""
import base64
import hashlib
import json

from common import router_post, latest_run_dir

MODEL = "cx/gpt-image-1.5"


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
        resp = router_post("/images/generations", {
            "model": MODEL,
            "prompt": idea["cover_prompt"],
            "size": "1024x1024",
            "n": 1,
        }, timeout=180)
        out_path.write_bytes(base64.b64decode(resp["data"][0]["b64_json"]))
    except (RuntimeError, KeyError, IndexError, ValueError) as e:
        print(f"image API недоступен ({e}); фолбэк-обложка"[:300])
        fallback_cover(idea["cover_prompt"], out_path)
    print(f"cover -> {out_path}")


if __name__ == "__main__":
    main()
