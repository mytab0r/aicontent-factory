#!/usr/bin/env python3
"""Шаг 3b: своя анимация для КАЖДОЙ обложки выпуска (одобрено владельцем 13.10).

Wan2.2 i2v на бесплатном HF ZeroGPU Space (диск ПК не используется), 3 с клип ->
ping-pong (вперёд+назад) = бесшовная петля runs/<run>/loop.mp4.
Любой сбой (квота ZeroGPU ~5 мин/день, Space лежит) -> выходим 0 без loop.mp4,
04_assemble собирает статичный кадр: выпуск важнее анимации.
ponytail: один публичный Space; при частых сбоях — Kaggle/Modal или локально на C:.
"""
import os
import shutil
import subprocess
import sys

from common import latest_run_dir

SPACE = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
MOTION = ("subtle cozy motion: rain or snow falls, lights flicker softly, steam rises, "
          "hair and fabric sway slightly, characters breathe and blink, static camera")


def motion_prompt(idea: dict) -> str:
    scene = (idea.get("cover_prompt") or "").split(", aesthetic")[0].strip()
    return f"{scene}. {MOTION}" if scene else MOTION


def main() -> None:
    import json
    run_dir = latest_run_dir()
    idea = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))
    try:
        from gradio_client import Client, handle_file
        c = Client(SPACE, token=os.environ.get("HF_TOKEN"), verbose=False)
        v, _ = c.predict(handle_file(str(run_dir / "cover.png")), motion_prompt(idea),
                         steps=6, duration_seconds=3.0, randomize_seed=True,
                         api_name="/generate_video")
        raw = run_dir / "anim_raw.mp4"
        shutil.copy(v["video"] if isinstance(v, dict) else v, raw)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-filter_complex",
                        "[0:v]reverse[r];[0:v][r]concat=n=2:v=1[v]", "-map", "[v]", "-an",
                        str(run_dir / "loop.mp4")], check=True)
        print(f"loop -> {run_dir / 'loop.mp4'}")
    except Exception as e:  # noqa: BLE001 — фолбэк на статику, причина в лог
        print(f"анимация пропущена, будет статичный кадр: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
