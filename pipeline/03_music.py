#!/usr/bin/env python3
"""Шаг 3: процедурная генерация lo-fi/ambient трека (WAV) без внешних моделей.

Почему процедурно, а не через готовую модель генерации музыки:
9router не предоставляет music-gen модель (проверено: нет ни одного
audio/music эндпоинта с рабочим backend). Suno/Udio — платные внешние
SaaS, что запрещено п.2 AGENTS.md без явного решения. Поэтому для MVP —
простой процедурный синтез (детерминированный, бесплатный, без лицензионных
рисков): случайные lo-fi аккорды на синусах с мягкой огибающей + шум винила
+ лёгкий RC-фильтр низких частот для "тёплого" звука.

Только numpy + stdlib wave — scipy.signal убран: на 1 vCPU сервере
scipy.signal.butter/lfilter подвешивает процесс (threadpool deadlock),
а готовый однополюсный фильтр даёт тот же "тёплый" эффект за O(n).

ponytail: это не "настоящая" музыка с мелодией/ударными — упрощение ради
MVP. Апгрейд (при появлении денег/нужды): подключить внешний music-gen API
(Suno/Udio/ElevenLabs Music) за этим же интерфейсом generate_track().
"""
import wave

import numpy as np

from common import latest_run_dir

SR = 44100
NOTE_A4 = 440.0

# lo-fi аккордовые прогрессии (semitones от A4, минорный септаккорд от каждой ступени)
PROGRESSIONS = [
    [0, -3, -5, -8],
    [0, -5, -3, -8],
    [0, -7, -5, -10],
]


def note_freq(semitones_from_a4: float) -> float:
    return NOTE_A4 * (2 ** (semitones_from_a4 / 12))


def chord_freqs(root_semitone: int) -> list[float]:
    intervals = [0, 3, 7, 10]  # минорный септаккорд
    return [note_freq(root_semitone + i - 24) for i in intervals]


def one_pole_lowpass(signal: np.ndarray, cutoff_hz: float = 2800, chunk: int = 2048) -> np.ndarray:
    """Простой RC low-pass: y[n] = y[n-1] + a*(x[n]-y[n-1]). Без scipy.

    Чистый python-цикл по сэмплам слишком медленный (1 vCPU), поэтому
    приближаем поблочно: внутри блока используем кумулятивную свёртку
    через экспоненциальное окно (векторизовано numpy), блоки стыкуем
    по последнему значению — для lo-fi эффекта точность не критична.
    """
    rc = 1.0 / (2 * np.pi * cutoff_hz)
    dt = 1.0 / SR
    a = dt / (rc + dt)
    out = np.empty_like(signal)
    prev = 0.0
    n = len(signal)
    # веса экспоненциального затухания внутри блока: (1-a)^k
    idx = np.arange(chunk)
    decay = (1 - a) ** idx
    for start in range(0, n, chunk):
        block = signal[start:start + chunk]
        m = len(block)
        d = decay[:m]
        # y[k] = a * sum_{j<=k} block[j] * (1-a)^(k-j) + prev*(1-a)^(k+1)
        weighted = block * a / d
        cum = np.cumsum(weighted) * d
        cum += prev * d * (1 - a)
        out[start:start + m] = cum
        prev = cum[-1]
    return out


def chord_wave(freqs: list[float], duration: float) -> np.ndarray:
    t = np.linspace(0, duration, int(SR * duration), endpoint=False)
    wave_ = np.zeros_like(t)
    for f in freqs:
        wave_ += np.sin(2 * np.pi * f * t) * 0.5
        wave_ += np.sin(2 * np.pi * f * 2 * t) * 0.05
    env = np.ones_like(t)
    fade = int(SR * 0.3)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return wave_ * env


def vinyl_noise(duration: float, level: float = 0.015) -> np.ndarray:
    n = int(SR * duration)
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 1, n)
    return noise * level


def generate_track(duration_sec: int = 60, seed: int = 0) -> np.ndarray:
    progression = PROGRESSIONS[seed % len(PROGRESSIONS)]
    bar_duration = 4.0
    bars_needed = int(np.ceil(duration_sec / bar_duration))

    chunks = []
    for i in range(bars_needed):
        root = progression[i % len(progression)]
        freqs = chord_freqs(root)
        chunks.append(chord_wave(freqs, bar_duration))
    track = np.concatenate(chunks)[: int(SR * duration_sec)]

    track = one_pole_lowpass(track, cutoff_hz=2800)
    track = track + vinyl_noise(duration_sec)

    peak = np.max(np.abs(track))
    if peak > 0:
        track = track / peak * 0.8
    return track


def write_wav(path, samples: np.ndarray) -> None:
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(pcm.tobytes())


def main() -> None:
    import os
    run_dir = latest_run_dir()
    duration = int(os.environ.get("TRACK_DURATION_SEC", "600"))  # 10 минут по умолчанию
    seed = abs(hash(run_dir.name)) % 1000
    track = generate_track(duration_sec=duration, seed=seed)

    out_path = run_dir / "track.wav"
    write_wav(out_path, track)
    print(f"track -> {out_path} ({duration}s)")


if __name__ == "__main__":
    main()
