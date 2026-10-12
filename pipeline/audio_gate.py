#!/usr/bin/env python3
"""Детерминированный гейт качества трека перед публикацией (kanban t_44de72aa).

Критерии приёмки:
  - одна тональность >= 85% 15-секундных окон;
  - разброс строя (tuning) <= 0.15 полутона;
  - нет секунд тише -45 dBFS (кроме 1 с в начале и 5 с финального фейда);
  - true peak <= -1 dBTP.

Почему так: аудит 4HB26c4yow0 — 4 независимых куска с разными seed дали
3 тональности на трек, строй плыл до +0.40 полутона, -56 dB дыры на стыках.

Тональность: хрома из STFT + профили Krumhansl-Kessler (24 ключа).
ponytail: параллельные мажор/минор (C major / A minor) = один звукоряд и
неразличимы для хромы на лоу-фае, поэтому доля считается по звукоряду
(key signature), а не по метке major/minor. Апгрейд — essentia/madmom key
detector, если появится реальный кейс модуляции в параллельный ключ.

Запуск: python3 audio_gate.py track.mp3 [--json out.json]; exit 0 = ok.
"""
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 22050
WIN_SEC = 15
KEY_SHARE_MIN = 0.85
TUNING_SPREAD_MAX = 0.15
TUNING_CORE_TOL = 0.03  # консенсус пиков внутри окна: ±3 цента
SILENCE_DB = -45.0
TRUE_PEAK_MAX = -1.0
HEAD_SKIP, TAIL_SKIP = 1, 5

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def write_wav(path, x: np.ndarray, sr: int) -> None:
    x = np.atleast_2d(x.T).T if x.ndim == 1 else x
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1] if pcm.ndim == 2 else 1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def decode(path, sr: int = SR) -> np.ndarray:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(out, dtype="<f4").astype(np.float64)


def _spectra(x: np.ndarray, n_fft: int = 8192, hop: int = 4096):
    win = np.hanning(n_fft)
    n = max(0, (len(x) - n_fft) // hop + 1)
    if n == 0:
        return np.zeros((0, n_fft // 2 + 1)), np.fft.rfftfreq(n_fft, 1 / SR), hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    return np.abs(np.fft.rfft(x[idx] * win, axis=1)), np.fft.rfftfreq(n_fft, 1 / SR), hop


def _key_of(chroma: np.ndarray):
    """-> (tonic 0..11, is_minor, signature 0..11 = тоника параллельного мажора)."""
    c = chroma - chroma.mean()
    best = (-2.0, 0, False)
    for t in range(12):
        for prof, minor in ((MAJ, False), (MIN, True)):
            p = np.roll(prof, t)
            r = float(np.dot(c, p - p.mean()) / (np.linalg.norm(c) * np.linalg.norm(p - p.mean()) + 1e-12))
            if r > best[0]:
                best = (r, t, minor)
    _, t, minor = best
    return t, minor, (t + 3) % 12 if minor else t


def _tuning(block: np.ndarray, freqs: np.ndarray) -> tuple[float, float] | None:
    """(строй окна в полутонах, доля пиков в консенсусе) или None.

    Плотный микс = тысячи пиков на окно с собственным шумом ±0.87 п/п,
    circular mean по всем показывает 0.3-0.4 (шум). Итог — консенсус:
    стартуем с circular mean, итеративно оставляем пики в tolerance,
    делаем ещё 2 круга (мода кругового распределения)."""
    band = (freqs > 150) & (freqs < 2500)
    devs, ws = [], []
    for frame in block:
        lm = np.log(frame + 1e-9)
        thr = frame[band].max() * 0.1 if frame[band].size else 0
        k = np.where(band[1:-1] & (frame[1:-1] > thr) & (frame[1:-1] > frame[:-2]) & (frame[1:-1] >= frame[2:]))[0] + 1
        for i in k:
            a, b, c = lm[i - 1], lm[i], lm[i + 1]
            d = 0.5 * (a - c) / (a - 2 * b + c + 1e-12)
            f = (i + d) * (freqs[1] - freqs[0])
            m = 12 * np.log2(f / 440.0)
            devs.append(m - np.round(m))
            ws.append(frame[i])
    if len(ws) < 100:
        return None
    d = np.array(devs)
    w = np.array(ws)
    for _ in range(2):
        med = float(np.angle(np.sum(w * np.exp(2j * np.pi * d))) / (2 * np.pi))
        rel = (d - med + 0.5) % 1 - 0.5
        sel = np.abs(rel) < TUNING_CORE_TOL
        if sel.sum() < max(50, len(d) // 100):
            break
        d, w = d[sel], w[sel]
    share = len(d) / len(ws)
    if len(d) < 50 or share < 0.05:  # консенсуса нет: шум/перкуссия, не строй
        return None
    med = float(np.angle(np.sum(w * np.exp(2j * np.pi * d))) / (2 * np.pi))
    return med, share


def analyze_pcm(x: np.ndarray) -> dict:
    freqs = np.fft.rfftfreq(8192, 1 / SR)
    pc = np.full(freqs.shape, -1)
    # хрома по МАГНИТУДЕ 80-1000 Гц: энергия (|X|^2) до 2 кГц давала
    # 0.6 на одном 240-с куске одного seed (хэт/шум/гребёнка тянут ключ);
    # 80-1000 Гц |X| = бас+гармония: 0.93 на нём же, old.mp3 (3 тональности) 0.47.
    ok = (freqs > 80) & (freqs < 1000)
    pc[ok] = np.mod(np.round(12 * np.log2(freqs[ok] / 440.0)) + 9, 12).astype(int)
    keys, tunings = [], []
    n = WIN_SEC * SR
    for s in range(0, len(x), n):  # по окну: вся матрица кадров 15-мин трека = ГБ RAM
        seg = x[s:s + n]
        if len(seg) < n // 2:
            continue
        block = _spectra(seg)[0]
        if block.sum() < 1e-6:
            continue
        spec = block.sum(0)
        chroma = np.array([spec[pc == i].sum() for i in range(12)])
        keys.append(_key_of(chroma))
        t = _tuning(block, freqs)
        if t is not None:
            tunings.append(t[0])

    sigs = [k[2] for k in keys]
    sig, key, key_share = None, None, 0.0
    if sigs:
        sig = max(set(sigs), key=sigs.count)
        key_share = sigs.count(sig) / len(sigs)
        labels = [f"{NAMES[t]} {'minor' if m else 'major'}" for t, m, s in keys if s == sig]
        key = max(set(labels), key=labels.count)
    # строй: разброс по ВСЕМ окнам с консенсусом (круговой, вокруг кругового
    # среднего). Прежнее «ядро ±3 цента» прятало дрейф, а tuning_share>=0.6
    # не набирал ни один реальный трек (один seed: 0.15) — убран.
    med, spread = 0.0, 1.0
    if tunings:
        tn = np.array(tunings)
        med = float(np.angle(np.exp(2j * np.pi * tn).mean()) / (2 * np.pi))
        rel = (tn - med + 0.5) % 1 - 0.5
        spread = float(rel.max() - rel.min())

    sec = len(x) // SR
    rms = np.sqrt(np.mean(x[: sec * SR].reshape(sec, SR) ** 2, axis=1) + 1e-20) if sec else np.zeros(0)
    db = 20 * np.log10(rms + 1e-12)
    body = db[HEAD_SKIP: max(HEAD_SKIP, sec - TAIL_SKIP)]
    return {
        "duration": round(len(x) / SR, 2),
        "windows": len(keys),
        "key": key,
        "key_share": round(key_share, 3) if sigs else 0.0,
        "signature": sig if sigs else None,
        "tuning_median": round(med, 3),
        "tuning_spread": round(spread, 3),
        "silent_seconds": int((body < SILENCE_DB).sum()),
        "min_second_db": round(float(body.min()), 1) if body.size else None,
    }


def loudness(path) -> dict:
    err = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    summary = err[err.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summary)
    p = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    f = lambda m: float(m.group(1)) if m and m.group(1) != "-inf" else float("-inf")  # noqa: E731
    return {"lufs": f(i), "true_peak": f(p)}


def check_file(path) -> dict:
    r = analyze_pcm(decode(path))
    r.update(loudness(path))
    fails = []
    if r["key_share"] < KEY_SHARE_MIN:
        fails.append(f"key_share {r['key_share']} < {KEY_SHARE_MIN}")
    if r["tuning_spread"] > TUNING_SPREAD_MAX:
        fails.append(f"tuning_spread {r['tuning_spread']} > {TUNING_SPREAD_MAX}")
    if r["silent_seconds"]:
        fails.append(f"silent_seconds {r['silent_seconds']} (< {SILENCE_DB} dB)")
    if r["true_peak"] > TRUE_PEAK_MAX:
        fails.append(f"true_peak {r['true_peak']} > {TRUE_PEAK_MAX} dBTP")
    r["fails"] = fails
    r["ok"] = not fails
    return r


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    r = check_file(argv[0])
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps(r, indent=2))
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
