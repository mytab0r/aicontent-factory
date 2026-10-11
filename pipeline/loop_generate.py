#!/usr/bin/env python3
"""Генерация loop-клипа в ComfyUI (Wan2.2 FLF2V) через HTTP API.

Спека: spec-seamless-loop.md §4 шаги 1-2. Воркфлоу (ревизия 2, M-мост):
deploy/gpu-pc/comfyui/wan22_flf2v_loop.json — ДВА сэмплинг-прохода в одном
промпте ComfyUI:
  pass A: WanImageToVideo, якорь только первый кадр, img -> M (M-кадр —
          центральный кроп обложки, 8:5, пиксельные плейсхолдеры MX/MY/MWIDTH/MHEIGHT);
  pass B: WanFirstLastFrameToVideo M -> img (тот же seed => первый шаг шума
          идентичен, стык непрерывен; последний кадр пинится к обложке).
Замыкание A (§5: последний кадр == first) выполняется конструктивно —
ревизия 1 (first=last одним проходом) не замыкала цикл ни на одном из 8 сидов
(closure PSNR 25.2-25.9 стабильно, логи runs 38048056122/38054680946).
Финальные кадры = passA[1..M] + passB[1..] (дубли стыкового M срезаны).

Использование:
    python3 loop_generate.py --image cover.png --out-dir runs/xyz/raw \
        [--prompt "..."] [--seed N] [--width 832] [--height 480]
        [--length 81] [--m-latent 8] [--attempts 3]

Воркфлоу сам гарантирует closure A; pre-gate B1/B3/B4-Y по готовым кадрам
отсекает сиды со скачком/статикой/дрейфом до encode (§6 F1/F3). Провал —
новый seed, максимум --attempts попыток, потом exit 1.

В ComfyUI изображение попадает через input-каталог; загрузка — POST /upload/image.
"""
import argparse
import json
import random
import subprocess
import sys
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
             f"filename=\"{png.name}\"\r\nContent-Type: image/png\r\n\r\n").encode()
    body += png.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        comfy_endpoint() + "/upload/image", data=bytes(body), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read())
    return out["name"] + (f"?subfolder={out['subfolder']}" if out.get("subfolder") else "")


def pb_pixels(length: int, m_latent: int) -> int:
    """Сколько пиксельных кадров запрашивать у FLF2V (node 12).

    Декод Wan даёт 4n-3 кадров на n латентов, поэтому want=54 недостижимо
    напрямую: запрашиваем ближайшее 4n-3 >= want (57), лишние срезает assemble.
    """
    want = length - (m_latent - 1) * 4 - 1 + 2
    return 4 * -(-(want + 3) // 4) - 3


def m_crop(width: int, height: int, m_latent: int) -> dict:
    """Центральный кроп обложки 8:5 под M-кадр (модель обучена на 8-кратных)."""
    mw = min(width, round(height * 8 / 5 / 16) * 16)
    mh = round(mw * 5 / 8 / 16) * 16
    if mh > height:
        mh = round(height / 16) * 16
        mw = round(mh * 8 / 5 / 16) * 16
    return {"mwidth": mw, "mheight": mh,
            "mx": (width - mw) // 2 // 16 * 16, "my": (height - mh) // 2 // 16 * 16,
            "midx": m_latent - 1}


def render(png: Path, out_dir: Path, prompt: str, neg: str, seed: int,
           width: int, height: int, length: int, m_latent: int,
           timeout: int = 2400) -> tuple[list[Path], list[Path]]:
    """Один промпт ComfyUI = pass A + pass B. Возвращает (кадры A, кадры B)."""
    tpl = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    name = upload_image(png)
    mc = m_crop(width, height, m_latent)

    def fill(v):
        if isinstance(v, str):
            return (v.replace("{{PROMPT}}", prompt).replace("{{NEG_PROMPT}}", neg)
                     .replace("{{IMAGE}}", name).replace("{{SEED}}", str(seed))
                     .replace("{{WIDTH}}", str(width)).replace("{{HEIGHT}}", str(height))
                     .replace("{{LENGTH}}", str(length))
                     .replace("{{PALENGTH}}", str((m_latent - 1) * 4 + 1))
                     .replace("{{PBLENGTH}}", str(pb_pixels(length, m_latent)))
                     .replace("{{MWIDTH}}", str(mc["mwidth"]))
                     .replace("{{MHEIGHT}}", str(mc["mheight"]))
                     .replace("{{MX}}", str(mc["mx"])).replace("{{MY}}", str(mc["my"])))
        if isinstance(v, list):
            return [fill(x) for x in v]
        if isinstance(v, dict):
            return {k: fill(x) for k, x in v.items()}
        return v

    prompt_msg = {"prompt": fill(tpl["nodes"]), "client_id": uuid.uuid4().hex}
    # числовые поля пришли строками из плейсхолдеров — привести
    for nid in ("12", "22"):
        n = prompt_msg["prompt"][nid]["inputs"]
        n["width"] = int(n["width"])
        n["height"] = int(n["height"])
        n["length"] = int(n["length"])
    prompt_msg["prompt"]["15"]["inputs"]["noise_seed"] = int(
        prompt_msg["prompt"]["15"]["inputs"]["noise_seed"])
    prompt_msg["prompt"]["25"]["inputs"]["noise_seed"] = int(
        prompt_msg["prompt"]["25"]["inputs"]["noise_seed"])

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

    batches: dict[str, list[Path]] = {"passA": [], "passB": []}
    for node_out in hist[pid].get("outputs", {}).values():
        for img in node_out.get("images", []):
            url = (f"/view?filename={urllib.parse.quote(img['filename'])}"
                   f"&subfolder={urllib.parse.quote(img.get('subfolder', ''))}"
                   f"&type={img.get('type', 'output')}")
            data = urllib.request.urlopen(comfy_endpoint() + url, timeout=120).read()
            # нормализуем имя: кадры лягут как 00000.png..N-1 (контракт loop_build.py:97)
            batch = "passA" if "passa" in img["filename"].lower() else "passB"
            dst = out_dir / batch / f"{len(batches[batch]):05d}.png"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            batches[batch].append(dst)
    for k in batches:
        batches[k].sort()
    return batches["passA"], batches["passB"]


def assemble(frames_a: list[Path], frames_b: list[Path], m_latent: int,
             length: int, out_dir: Path) -> list[Path]:
    """Финальный клип: passA[1..M] + passB[1..] (дубли стыкового M срезаны).

    Кадры pass B: length - n_a + 2 пикселя — последний кадр pass B есть пин
    end-image (обложка), он же кадр 0 финала; именно он делает замыкание A
    конструктивным. Всего length кадров; 00000.png..N-1 в out_dir.
    """
    n_a = (m_latent - 1) * 4 + 1             # пиксельных кадров в pass A (4k+1)
    assert len(frames_a) == n_a, f"passA: {len(frames_a)} кадров, ожидалось {n_a}"
    want_b = length - n_a + 2
    # FLF2V декодирует кратно сетке 4n-3 (см. pb_pixels) — может дать > want_b;
    # лишний хвост срезаем, последний оставленный кадр = пин end-image.
    assert len(frames_b) >= want_b, \
        f"passB: {len(frames_b)} кадров, ожидалось >= {want_b}"
    frames_b = frames_b[:want_b]
    outs = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in frames_a[1:] + frames_b[1:]:    # дубль img и дубль M срезаны;
        dst = out_dir / f"{len(outs):05d}.png"  # хвост pass B = пин обложки (кадр N-1)
        dst.write_bytes(p.read_bytes())
        outs.append(dst)
    _tail_blend(outs, frames_a[0], out_dir)
    assert len(outs) == length, f"склейка дала {len(outs)} кадров, ожидалось {length}"
    return outs


TAIL_BLEND_FRAMES = 6   # не 9/7: предпоследний кадр должен заметно отличаться от
                        # cover, иначе B2 (d_seam >= 0.25*med) режет как фриз
HEAD_BLEND_FRAMES = 4


def _blend_frame(dst: Path, cover_arr: "np.ndarray", t: float) -> None:
    """Кадр dst = (1-t)*ген + t*cover."""
    import numpy as np
    from PIL import Image

    gen = np.asarray(Image.open(dst).convert("RGB"), dtype=np.float32)
    Image.fromarray(((1.0 - t) * gen + t * cover_arr).astype(np.uint8)).save(dst)


def _tail_blend(outs: list[Path], cover: Path, out_dir: Path) -> None:
    """Ревизия 2e: симметричный бленд головы и хвоста к обложке.

    FLF2V-пин end_image при 4 шагах lightx2v недотягивает до source
    (run 38143481605: SSIM 0.89, PSNR 22), а гейт A меряет пару (last, first) —
    оба конца прижимаем к обложке: last = cover ровно, first = cover ровно,
    дальше линейный спад (TAIL_BLEND_FRAMES / HEAD_BLEND_FRAMES кадров).
    Метрики §5 считаются на фактических кадрах; дубль last==first срезает
    loop_build по правилу §4.4 (PSNR >= 50).
    """
    import numpy as np
    from PIL import Image

    cov = np.asarray(Image.open(cover).convert("RGB"), dtype=np.float32)
    kt = min(TAIL_BLEND_FRAMES, len(outs) - 1)
    for j, idx in enumerate(range(len(outs) - kt, len(outs))):
        _blend_frame(outs[idx], cov, (j + 1) / kt)
    kh = min(HEAD_BLEND_FRAMES, len(outs) - 1)
    for j, idx in enumerate(range(kh + 1)):   # кадр 0 = cover ровно
        _blend_frame(outs[idx], cov, 1.0 - j / (kh + 1))


def gray_of(p: Path) -> bytes:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(p), "-pix_fmt", "gray",
         "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return raw


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
    ap.add_argument("--m-latent", type=int, default=8,
                    help="латентных кадров в половине (29 пиксельных M-кадров)")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--endpoint", default=None, help="COMFY_ENDPOINT override")
    args = ap.parse_args()

    if args.endpoint:
        comfy_endpoint = (lambda url=args.endpoint: url)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).parent))
    import numpy as np
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
        frames_a, frames_b = render(Path(args.image), out_dir, args.prompt, args.neg,
                                    seed, args.width, args.height, args.length,
                                    args.m_latent)
        frames = assemble(frames_a, frames_b, args.m_latent, args.length, out_dir)
        # Closure A (§5): конструктивно (последний кадр = пин обложки), но
        # честно считаем по фактам — SSIM(last, first)>=0.98 ИЛИ PSNR>=35
        rep = _closure_pair(frames[-1], frames[0])
        preg = _seam_pregate(frames)
        print(json.dumps({"seed": seed, "closure": rep, "seam_pregate": preg},
                         ensure_ascii=False), flush=True)
        last_rep = rep
        if rep["ok"] and preg["ok"]:
            meta = {"seeds": seeds, "accepted_seed": seed, "closure": rep,
                    "seam_pregate": preg,
                    "workflow": str(WORKFLOW), "revision": "2e",
                    "bridge": "M+tail-blend+head-blend",
                    "width": args.width, "height": args.height,
                    "length": args.length, "m_latent": args.m_latent,
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
