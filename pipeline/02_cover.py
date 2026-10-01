#!/usr/bin/env python3
"""Шаг 2: сгенерировать обложку (PNG) по cover_prompt из idea.json через 9router image API."""
import base64
import json

from common import router_post, latest_run_dir

MODEL = "cx/gpt-image-1.5"


def main() -> None:
    run_dir = latest_run_dir()
    idea = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))

    resp = router_post("/images/generations", {
        "model": MODEL,
        "prompt": idea["cover_prompt"],
        "size": "1024x1024",
        "n": 1,
    }, timeout=180)

    b64 = resp["data"][0]["b64_json"]
    out_path = run_dir / "cover.png"
    out_path.write_bytes(base64.b64decode(b64))
    print(f"cover -> {out_path}")


if __name__ == "__main__":
    main()
