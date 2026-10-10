#!/usr/bin/env python3
"""Генерация loop-клипа в ComfyUI (Wan2.2 FLF2V) через HTTP API.

Спека: spec-seamless-loop.md §4 шаг 1-2. Воркфлоу:
deploy/gpu-pc/comfyui/wan22_flf2v_loop.json (API-формат, плейсхолдеры
{{PROMPT}} {{NEG_PROMPT}} {{IMAGE}} {{SEED}} {{WIDTH}} {{HEIGHT}} {{LENGTH}}).

Использование:
    python3 loop_generate.py --image cover.png --out-dir runs/xyz/raw \
        [--prompt "..."] [--seed N] [--width 832] [--height 480]
        [--length 81] [--attempts 3]

Closure-метрика A (§5) проверяется здесь же по вынутым кадрам:
провал -> новый seed, максимум --attempts попыток, потом exit 1.

В ComfyUI изображение попадает через input-каталог; загрузка — POST /upload/image.
"""
import argparse
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / "deploy" / "gpu-pc" / "comfyui" / "wan22_flf2v_loop.json"

DEFAULT_PROMPT = (
    "static camera, subtle continuous motion in the scene, gentle ambient "
    "movement, soft lighting, no camera movement, seamless loop, constant brightness, constant exposure, no flicker"
)
DEFAULT_NEG = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，画风，突然的剧烈运动，镜头切换，亮度变化，闪烁，曝光变化，"
    "抖动，最差质量，低质量，JPEG压缩残留，畸形的，毁容的"
)


def comfy_endpoint() -> str:
    import os
    return os.environ.get("COMFY_ENDPOINT", "http://127.0.0.1:8188").rstrip("/")


def _api(path: str, timeout: int = 60):
    with urllib.request.urlopen(comfy_endpoint() + path, timeout=timeout) as r:
        return json.loads(r.read())


def upload_image(png: Path) -> str:
    """POST /upload/image, вернуть имя, видимое ноде LoadImage."""
    boundary = uuid.uuid4().hex
    body = bytearray()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
             f"filename=\"{png.name}\"\r\nContent-Type: image/png\r\n\r\n"
             ).encode()
    body += png.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        comfy_endpoint() + "/upload/image", data=bytes(body), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read())
    return out["name"] + (f"?subfolder={out['subfolder']}" if out.get("subfolder") else "")


def render(png: Path, out_dir: Path, prompt: str, neg: str, seed: int,
           width: int, height: int, length: int, timeout: int = 1500) -> list[Path]:
    """Один прогон воркфлоу; возвращает пути к PNG-кадрам (скачанным локально)."""
    tpl = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    name = upload_image(png)

    def fill(v):
        if isinstance(v, str):
            return (v.replace("{{PROMPT}}", prompt).replace("{{NEG_PROMPT}}", neg)
                     .replace("{{IMAGE}}", name).replace("{{SEED}}", str(seed))
                     .replace("{{WIDTH}}", str(width)).replace("{{HEIGHT}}", str(height))
                     .replace("{{LENGTH}}", str(length)))
        if isinstance(v, list):
            return [fill(x) for x in v]
        if isinstance(v, dict):
            return {k: fill(x) for k, x in v.items()}
        return v

    prompt_msg = {"prompt": fill(tpl["nodes"]), "client_id": uuid.uuid4().hex}
    # числовые поля пришли строками из плейсхолдеров — привести
    n12 = prompt_msg["prompt"]["12"]["inputs"]
    n12["width"] = int(n12["width"])
    n12["height"] = int(n12["height"])
    n12["length"] = int(n12["length"])
    prompt_msg["prompt"]["15"]["inputs"]["noise_seed"] = int(
        prompt_msg["prompt"]["15"]["inputs"]["noise_seed"])

    req = urllib.request.Request(
        comfy_endpoint() + "/prompt", data=json.dumps(prompt_msg).encode(),
        method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ComfyUI /prompt HTTP {e.code}: {e.read().decode()[:2000]}")
    pid = resp["prompt_id"]

    t0 = time.time()
    hist: dict = {}
    while time.time() - t0 < timeout:
        time.sleep(5)
        hist = _api(f"/history/{pid}")
        if pid in hist:
            st = hist[pid].get("status", {})
            if st.get("completed"):
                break
            if st.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI error: {json.dumps(hist[pid].get('status'))[:2000]}")
    else:
        raise RuntimeError(f"timeout {timeout}s waiting for {pid}")

    outs = []
    for node_out in hist[pid].get("outputs", {}).values():
        for img in node_out.get("images", []):
            url = (f"/view?filename={urllib.parse.quote(img['filename'])}"
                   f"&subfolder={urllib.parse.quote(img.get('subfolder', ''))}"
                   f"&type={img.get('type', 'output')}")
            data = urllib.request.urlopen(comfy_endpoint() + url, timeout=120).read()
            # нормализуем имя: кадры лягут как 00000.png..N-1 (контракт loop_build.py:97)
            dst = out_dir / f"{len(outs):05d}.png"
            dst.write_bytes(data)
            outs.append(dst)
    outs.sort()
    return outs


def main() -> None:
    global comfy_endpoint
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--neg", default=DEFAULT_NEG)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--length", type=int, default=81)
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--endpoint", default=None, help="COMFY_ENDPOINT override")
    args = ap.parse_args()

    if args.endpoint:
        comfy_endpoint = (lambda url=args.endpoint: url)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).parent))
    import seam_check

    # фиксированный --seed не закрепляет последующие попытки: рандомные сида —
    # база для честной калибровки порогов B (§5), cache-hit с одним сидом
    # выдаёт вырожденные метрики (med_jump_y ~0)
    seeds = []
    last_rep = None
    for attempt in range(args.attempts):
        seed = (args.seed + attempt) if args.seed is not None else random.randrange(2**31)
        seeds.append(seed)
        print(f"[attempt {attempt + 1}/{args.attempts}] seed={seed}", flush=True)
        frames = render(Path(args.image), out_dir, args.prompt, args.neg, seed,
                        args.width, args.height, args.length)
        assert len(frames) == args.length, f"ожидалось {args.length} кадров, пришло {len(frames)}"
        # Closure A (§5): SSIM(last, first)>=0.98 ИЛИ PSNR>=35 dB
        rep = _closure_pair(frames[-1], frames[0])
        preg = _seam_pregate(frames)
        print(json.dumps({"seed": seed, "closure": rep, "seam_pregate": preg},
                         ensure_ascii=False), flush=True)
        last_rep = rep
        if rep["ok"] and preg["ok"]:
            meta = {"seeds": seeds, "accepted_seed": seed, "closure": rep,
                    "seam_pregate": preg,
                    "workflow": str(WORKFLOW), "width": args.width,
                    "height": args.height, "length": args.length,
                    "prompt": args.prompt, "neg": args.neg,
                    "frames": [str(p) for p in frames]}
            (out_dir / "generate_meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"OK seed={seed} closure={rep}", flush=True)
            return
    print(f"closure fail после {args.attempts} попыток: {last_rep}", file=sys.stderr)
    raise SystemExit(1)


def _closure_pair(last_png: Path, first_png: Path) -> dict:
    """Метрика A на паре PNG (Y-канал, полный размер)."""
    import numpy as np

    import seam_check

    def gray(p: Path) -> np.ndarray:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(p), "-pix_fmt", "gray",
             "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(p)],
            capture_output=True, text=True, check=True).stdout.strip()
        w, h = map(int, out.split("x"))
        return np.frombuffer(raw, dtype=np.uint8).reshape(h, w)

    return seam_check.closure_metrics(gray(last_png), gray(first_png))


def _seam_pregate(frames: list) -> dict:
    """Pre-gate B1/B3 (+Y-часть B4) по raw-кадрам до encode (§5)."""
    import numpy as np

    import seam_check

    def gray(p: Path) -> np.ndarray:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(p), "-pix_fmt", "gray",
             "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.uint8)

    ys = [gray(p) for p in frames]
    yavg = [float(y.mean()) for y in ys]
    rep = seam_check.seam_metrics(ys, yavg=np.array(yavg))
    # Y-дрейф (B4) виден уже на raw-кадрах; UV-дрейф гоняет check_file по loop.mp4
    rep["ok"] = all(c["ok"] for c in rep["checks"]
                    if c["id"] in ("B1", "B3", "B4"))
    return rep


if __name__ == "__main__":
    main()
