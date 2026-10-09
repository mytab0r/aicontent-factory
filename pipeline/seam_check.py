#!/usr/bin/env python3
"""Метрики шва бесконечного цикла (спека spec-seamless-loop.md §5 A/B).

Только numpy + ffmpeg (никаких новых зависимостей). Кадры декодируются
ffmpeg в raw gray/Y-плейн и считаются попарно.

Использование:
    python3 seam_check.py loop.mp4 [--json seam_report.json]
    python3 seam_check.py --selftest

Метрики (§5):
A. closure_metrics(last, first): SSIM>=0.98 ИЛИ PSNR>=35 dB (raw-клип).
B. seam_metrics(frames) на loop.mp4:
   B1 нет скачка:    d_seam <= 2*med
   B2 нет дубля:     d_seam >= 0.25*med и PSNR(N-1,0) < 50 dB
   B3 анимация:      median PSNR соседних < 50 dB
   B4 нет дрейфа:    |YAVG_i - YAVG_0| <= 6, |UAVG_i - UAVG_0|/|VAVG| <= 4;
                     скачок YAVG на стыке <= 2*median скачка соседей
Провал любой из B1-B4 -> exit 1 (для A есть closure_metrics отдельно).
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np


def _decode_raw(path: str | Path, pix_fmt: str, size: tuple[int, int],
                extract: str | None = None) -> np.ndarray:
    """Декодировать видео в raw uint8-буфер (1D numpy).

    extract: 'y'|'u'|'v' — вынуть один план (иначе чередование Y/U/V по кадрам
    ломает наивную нарезку буфера).
    """
    w, h = size
    vf = f"scale={w}:{h}:flags=bilinear,format=yuv444p"
    if extract:
        vf += f",extractplanes={extract}"
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vf", vf,
           "-pix_fmt", pix_fmt, "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8)


def read_frames_gray(path: str | Path, size: tuple[int, int]) -> list[np.ndarray]:
    w, h = size
    buf = _decode_raw(path, "gray", (w, h))
    n = len(buf) // (w * h)
    return [buf[i * w * h:(i + 1) * w * h].reshape(h, w) for i in range(n)]


def read_planes(path: str | Path, size: tuple[int, int],
                plane: str) -> np.ndarray:
    """Один план ('y'|'u'|'v') как (n, h, w); chroma масштабируется до размера Y."""
    w, h = size
    buf = _decode_raw(path, "gray", (w, h), extract=plane)
    n = len(buf) // (w * h)
    return buf[:n * w * h].reshape(n, h, w)


def _decode_with_scale(path: str | Path, pix_fmt: str, size: tuple[int, int]) -> bytes:
    w, h = size
    cmd = ["ffmpeg", "-v", "error", "-i", str(path),
           "-vf", f"scale={w}:{h}:flags=bilinear",
           "-pix_fmt", pix_fmt, "-f", "rawvideo", "-"]
    return subprocess.run(cmd, capture_output=True, check=True).stdout


def video_size(path: str | Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split("x")
    return int(w), int(h)


def _mse(a: np.ndarray, b: np.ndarray) -> float:
    d = a.astype(np.float64) - b.astype(np.float64)
    return float(np.mean(d * d))


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = _mse(a, b)
    if mse == 0:
        return 99.0
    return 10.0 * np.log10(255.0 * 255.0 / mse)


def ssim_global(a: np.ndarray, b: np.ndarray) -> float:
    """Глобальный SSIM по Y (одна гауссова статистика, C1/C2 как в статье)."""
    x = a.astype(np.float64)
    y = b.astype(np.float64)
    mx, my = float(x.mean()), float(y.mean())
    vx, vy = float(x.var()), float(y.var())
    cxy = float(((x - mx) * (y - my)).mean())
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    num = (2 * mx * my + c1) * (2 * cxy + c2)
    den = (mx * mx + my * my + c1) * (vx + vy + c2)
    return num / den


def closure_metrics(last: np.ndarray, first: np.ndarray) -> dict:
    """Метрика A (§5): SSIM>=0.98 ИЛИ PSNR>=35 dB."""
    p = psnr(last, first)
    s = ssim_global(last, first)
    ok = s >= 0.98 or p >= 35.0
    return {"psnr": round(p, 2), "ssim": round(s, 4), "ok": bool(ok)}


def seam_metrics(frames: list[np.ndarray], yavg: np.ndarray | None = None,
                 uavg: np.ndarray | None = None,
                 vavg: np.ndarray | None = None) -> dict:
    """Метрики B1-B4 (§5) по списку Y-кадров loop.mp4.

    yavg/uavg/vavg — средние по кадру (для B4); если не переданы, считаются
    из frames (только Y; UV-дрейф тогда не проверяется — проверяющий
    вызывает check_file, который передаёт полные планы).
    """
    n = len(frames)
    assert n >= 4, f"слишком мало кадров: {n}"
    d = [_mse(frames[i], frames[i + 1]) for i in range(n - 1)]
    med = float(np.median(d))
    d_seam = _mse(frames[-1], frames[0])
    p_seam = psnr(frames[-1], frames[0])
    nb_psnr = [psnr(frames[i], frames[i + 1]) for i in range(n - 1)]
    med_nb_psnr = float(np.median(nb_psnr))

    checks = []
    # B1 нет скачка
    checks.append({"id": "B1", "ok": bool(d_seam <= 2.0 * med),
                   "d_seam": round(d_seam, 1), "med": round(med, 1),
                   "ratio": round(d_seam / med, 3) if med else None})
    # B2 нет фриза/дубля
    ok_b2 = bool(d_seam >= 0.25 * med) and bool(p_seam < 50.0)
    checks.append({"id": "B2", "ok": ok_b2,
                   "d_seam": round(d_seam, 1), "p_seam": round(p_seam, 2)})
    # B3 анимация, не статика
    checks.append({"id": "B3", "ok": bool(med_nb_psnr < 50.0),
                   "median_neighbor_psnr": round(med_nb_psnr, 2)})
    # B4 нет дрейфа яркости/цвета
    if yavg is not None:
        drift_y = float(np.max(np.abs(yavg - yavg[0]))) if n else 0.0
        jump_y = abs(float(yavg[-1]) - float(yavg[0]))
        med_jump_y = float(np.median([abs(yavg[i + 1] - yavg[i])
                                      for i in range(n - 1)]))
        ok_y = drift_y <= 6.0 and jump_y <= 2.0 * med_jump_y
        if uavg is not None and vavg is not None:
            drift_u = float(np.max(np.abs(uavg - uavg[0])))
            drift_v = float(np.max(np.abs(vavg - vavg[0])))
        else:
            drift_u = drift_v = 0.0
        checks.append({"id": "B4", "ok": bool(ok_y and drift_u <= 4.0
                                             and drift_v <= 4.0),
                       "drift_y": round(drift_y, 2),
                       "drift_u": round(drift_u, 2),
                       "drift_v": round(drift_v, 2),
                       "jump_y": round(jump_y, 2),
                       "med_jump_y": round(med_jump_y, 3)})
    failures = [c for c in checks if not c["ok"]]
    return {"n_frames": n, "checks": checks, "failures": failures,
            "ok": not failures}


def check_file(path: str | Path, downscale: int = 2) -> dict:
    """Метрики B по файлу loop.mp4: full decode, Y+UV-планы.

    downscale: во сколько раз сжать кадры перед MSE (скорость; SSIM/PSNR
    d-метрики относительные, пороги v1 калибруются на этой же конфигурации).
    """
    w0, h0 = video_size(path)
    w, h = w0 // downscale, h0 // downscale
    y = read_planes(path, (w, h), "y")
    u = read_planes(path, (w, h), "u")
    v = read_planes(path, (w, h), "v")
    yavg = y.mean(axis=(1, 2))
    uavg = u.mean(axis=(1, 2))
    vavg = v.mean(axis=(1, 2))
    return seam_metrics(list(y), yavg=yavg, uavg=uavg, vavg=vavg)


def closure_file(path: str | Path, downscale: int = 2) -> dict:
    """Метрика A по файлу raw-клипа (последний кадр vs первый)."""
    w0, h0 = video_size(path)
    w, h = w0 // downscale, h0 // downscale
    frames = read_frames_gray(path, (w, h))
    assert len(frames) >= 2, "менее 2 кадров"
    return closure_metrics(frames[-1], frames[0])


def selftest() -> bool:
    """Один assert-самотест (§8): идеальный цикл проходит, скачок нет.

    Синтетика та же, что в §8 спеки: движущаяся синусоида 320x180.
    """
    import subprocess
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "loop.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
             "color=gray:s=320x180:r=24,geq=lum='128+60*sin(2*PI*(X/320+T/2))'"
             ":cb=128:cr=128", "-frames:v", "48", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-crf", "16", str(p)],
            capture_output=True, check=True)
        good = check_file(p)
        assert good["ok"], good
        # хвост без возврата: период волны = 48 кадров, конец не совпадает
        # с началом, но монотонная фаза может дать d_seam ~ med (B1 молчит).
        # поэтому для "скачка" склеиваем первый кадр с кадром из противоположной
        # фазы: через -vf select вынимаем кадры 0..41, но подменяем последний
        # кадр на кадр 24 (пик волны против нуля) — точный анти-паттерн F3.
        # Проще: сгенерить независимый клип с другой фазой и склеить concat.
        phase = Path(td) / "phase.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
             "color=gray:s=320x180:r=24,geq=lum='128+60*sin(2*PI*(X/320+(T+1)/2))'"
             ":cb=128:cr=128", "-frames:v", "1", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-crf", "16", str(phase)],
            capture_output=True, check=True)
        lst = Path(td) / "list.txt"
        first = Path(td) / "first.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(p), "-frames:v", "41",
             "-c:v", "libx264", "-crf", "16", str(first)],
            capture_output=True, check=True)
        lst.write_text(f"file '{first}'\nfile '{phase}'\n")
        bad = Path(td) / "bad.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i",
             str(lst), "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
             str(bad)], capture_output=True, check=True)
        rep = check_file(bad)
        assert not rep["ok"] and any(f["id"] == "B1" for f in rep["failures"]), rep
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("loop", nargs="?", help="loop.mp4 для проверки")
    ap.add_argument("--json", dest="json_out", help="куда писать seam_report.json")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        ok = selftest()
        print("selftest OK" if ok else "selftest FAIL")
        raise SystemExit(0 if ok else 1)
    if not args.loop:
        ap.error("нужен loop.mp4 или --selftest")
    rep = check_file(args.loop)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    raise SystemExit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
