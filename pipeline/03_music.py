#!/usr/bin/env python3
"""Шаг 3: lo-fi трек через ACE-Step (HF Space, бесплатный публичный API).

История решения — см. docs/DECISIONS.md п.1 (апдейт):
изначально был чистый numpy-синтез (аккорды на синусах + шум) — качество
признано слабым владельцем ("просто арпеджио+шум, без мелодии/ударных").
Ресёрч актуального рынка (2026): MusicGen — CC-BY-NC (не годится для
монетизации), Stable Audio Open — коммерческая лицензия ОК, но нужна своя
GPU (её нет, 1 vCPU хост). Suno — нет официального API, только
реверс-инженерные обёртки (ToS-риск + юридическая неопределённость вокруг
данных обучения, сейчас в суде с лейблами) — отклонено.

Выбор: ACE-Step (github.com/ace-step/ACE-Step, Apache-2.0, честно заявлен
коммерчески пригодным) через публичный HF Space `ACE-Step/ACE-Step`
(ZeroGPU, бесплатно) по `gradio_client`. Проверено вживую: полный
инструментальный трек 45-60с генерируется за 15-35 секунд (в основном
сетевая/очередная задержка, сама диффузия ~3с) — с большим запасом для
1 видео/день. Жанр-специфичный промпт (не постобработка FFmpeg) даёт
звучание, принятое владельцем после A/B теста 3 вариантов.

ponytail: HF Space — бесплатный общий ресурс без SLA (может тормозить при
чужой нагрузке). Апгрейд при нужде: платный Space/Replicate с тем же
интерфейсом generate_track(), или self-host на домашнем GPU через туннель.
"""
import os

from gradio_client import Client

from common import latest_run_dir

SPACE = "ACE-Step/ACE-Step"

# Под-жанры внутри lo-fi-зонтика — ротация для разнообразия звучания
# (и чтобы не попасть под YouTube spam-policy "identical background music
# across many videos").
# Под-жанры — НЕ ограничено lofi-hip-hop-зонтиком. Конкурентный анализ
# (docs/DECISIONS.md п.5) показал, что самые доходные соседние ниши на
# YouTube (nature ambient, meditation/healing, easy-listening piano) не
# завязаны на lofi-поджанр вообще, и именно они менее насыщены в 2026м,
# чем классический lofi hip-hop. ACE-Step берёт любой текстовый
# жанр-промпт через тот же generate_track() — пайплайн не меняется.
GENRE_PROMPTS = {
    "anime lofi": (
        "anime lofi, soft rhodes piano melody, gentle boom bap drums with "
        "swing, warm bassline, vinyl noise, tape hiss, A minor, 82 BPM, "
        "instrumental, no vocals, cozy, nostalgic, study beats, Lofi Girl style"
    ),
}
# ponytail: 8 жанров из конкурентного анализа (DECISIONS.md п.5) отключены
# из прод-ротации — они никогда не проходили A/B прослушивание владельцем
# (одобрен был только "anime lofi"). Черновики — ниже, в CANDIDATE_GENRE_PROMPTS,
# включать обратно в GENRE_PROMPTS по одному, только после присланного
# семпла и явного одобрения владельцем.
# ponytail: тональности ниже поправлены на major по РЕАЛЬНЫМ измеренным
# данным (tunebat.com, digmyloop.com — аудиоанализ, не стереотип жанра):
# топовый Lofi Girl трек = C#major/82BPM (не A minor, как было изначально);
# Nujabes "Luv(sic)" = F major/92BPM (не F minor). "Минор = меланхолия" был
# моей стереотипной догадкой без проверки, не экспертным выбором. Прод-жанр
# "anime lofi" (GENRE_PROMPTS выше) НЕ тронут здесь намеренно — его смена
# тональности тоже требует нового A/B семпла, не блиц-правки.
CANDIDATE_GENRE_PROMPTS = {
    "jazzhop": (
        "nujabes style lofi hip hop, jazzy piano chords extended m7 maj9, "
        "boom bap swing drums, kick snare groove, warm upright bass, vinyl "
        "crackle, tape saturation, F major, 92 BPM, instrumental, no vocals, "
        "melancholic, dusty texture"
    ),
    "deep focus ambient": (
        "deep focus ambient lofi, slow pads, minimal piano, soft filtered "
        "drums, warm sub bass, vinyl crackle, D minor, 70 BPM, instrumental, "
        "no vocals, spacious, meditative, calm study music"
    ),
    "chillhop": (
        "chillhop, mellow electric piano, laid back boom bap groove, "
        "soulful chords maj7, warm bass, vinyl texture, tape warmth, "
        "C major, 85 BPM, instrumental, no vocals, relaxed, smooth"
    ),
    "rainy night lofi": (
        "rainy night lofi, soft rhodes and muted guitar, slow swung drums, "
        "warm round bass, vinyl crackle, light rain ambience, G minor, "
        "75 BPM, instrumental, no vocals, introspective, cozy, late night"
    ),
    # Ниши из конкурентного анализа (DECISIONS.md п.5), не lofi-derived:
    "nature ambient": (
        "nature ambient soundscape, soft sustained pads, distant birdsong, "
        "gentle flowing water texture, no drums, no percussion, minimal "
        "variation designed to loop seamlessly, warm airy, slow and "
        "unhurried, instrumental, no vocals, relaxing"
    ),
    "meditation healing": (
        "meditation and healing music, slow solo piano phrases with long "
        "decay, soft string pad underneath, 60 BPM, no drums, no vocals, "
        "spacious reverb, calm and grounding, gentle, instrumental"
    ),
    "easy listening piano": (
        "easy listening solo piano, warm and gentle melodic phrases, light "
        "rubato, soft room reverb, no drums, no vocals, 65 BPM, relaxed, "
        "comforting, instrumental"
    ),
    "sleep ambient": (
        "deep sleep ambient, very slow evolving drone pad, no percussion, "
        "no sudden dynamic changes, extremely minimal variation designed to "
        "loop seamlessly, soft low frequencies, instrumental, no vocals, "
        "hypnotic and slow"
    ),
}


def genre_for_mood(mood: str) -> tuple[str, str]:
    """Детерминированный выбор под-жанра по mood (воспроизводимо, но разнообразно)."""
    names = list(GENRE_PROMPTS.keys())
    idx = abs(hash(mood)) % len(names)
    name = names[idx]
    return name, GENRE_PROMPTS[name]


def ace_endpoint() -> tuple[str, str | None]:
    """Endpoint ACE-Step: локальный GPU-ПК (ACE_ENDPOINT) или HF Space.

    Локальный ACE-Step (домашний ПК, RTX 5070 через Tailscale) — тот же
    Gradio-интерфейс и те же параметры, что у HF Space: gradio_client
    совместим, пайплайн не меняется. Локальный вызов без токена.
    """
    local = os.environ.get("ACE_ENDPOINT")
    if local:
        return local, None
    return SPACE, os.environ.get("HF_TOKEN") or None


INFER_STEPS = 60  # было 27: аудит 4HB26c4yow0 — грязь/дрейф строя на 27 шагах


def generate_track(prompt: str, duration_sec: int, seed: int | None = None,
                   client_cls=Client) -> str:
    """text2music одним вызовом, возвращает путь к аудио (временный файл gradio)."""
    url, token = ace_endpoint()
    try:
        client = client_cls(url, token=token)
    except Exception as e:  # ПК выключен/DNS/туннель — не валим выпуск
        if url == SPACE:
            raise
        print(f"ACE {url} недоступен ({type(e).__name__}: {e}); HF Space фолбэк"[:300])
        client = client_cls(SPACE, token=os.environ.get("HF_TOKEN") or None)
    result = client.predict(
        audio_duration=float(duration_sec),
        prompt=prompt,
        lyrics="[instrumental]",
        infer_step=INFER_STEPS,
        guidance_scale=15.0,
        scheduler_type="euler",
        cfg_type="apg",
        omega_scale=10.0,
        manual_seeds=str(seed) if seed is not None else None,
        guidance_interval=0.5,
        guidance_interval_decay=0.0,
        min_guidance_scale=3.0,
        use_erg_tag=True,
        use_erg_lyric=False,
        use_erg_diffusion=True,
        oss_steps=None,
        guidance_scale_text=0.0,
        guidance_scale_lyric=0.0,
        audio2audio_enable=False,
        ref_audio_strength=0.5,
        ref_audio_input=None,
        lora_name_or_path="none",
        api_name="/__call__",
    )
    return result[0]


# ---- связная генерация long-form (kanban t_44de72aa) ----
# Было: N независимых кусков с разными seed -> 3 тональности на трек, дрейф
# строя до 0.4 полутона, -56 dB дыры на стыках (аудит 4HB26c4yow0).
# Пробовали ACE-Step extend-цепочку: тональность держит, но каждый extend
# добавляет гребёнку 86.13 Гц (44100/512, +15-18 dB над фоном против 4-7 у
# text2music) и уводит строй на 0.3 п/п — отклонено (A/B run 38195847121).
# Стало (вариант 2 ТЗ): база = text2music CHUNK_SEC одним seed; остальные
# куски = audio2audio от базы (ref_audio, свой seed) — вариации того же
# материала: одна тональность, один строй, без гребёнки. На кусок до
# CANDIDATES seed'ов, берётся первый совпавший с базой по звукоряду, строю
# (TUNING_TOL) и без тишины. Стыки — equal-power crossfade XFADE_SEC.
# Финал: двухпроходный loudnorm -14 LUFS / TP -2 (запас под mp3 overshoot).
CHUNK_SEC = 240  # лимит ACE-Step на вызов
XFADE_SEC = 4
CANDIDATES = 3
A2A_STRENGTH = 0.5
TUNING_TOL = 0.075
SR = 44100
TARGET_LUFS, TARGET_TP = -14.0, -2.0


def _read(path) -> "np.ndarray":
    import subprocess
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, 2).copy()


def _trim_tail_silence(x, db: float = -40.0):
    """Срезает тихий хвост (модель гасит звук к концу куска) — иначе дыра на стыке."""
    import numpy as np
    sec = len(x) // SR
    rms = np.sqrt(np.mean(x[: sec * SR].reshape(sec, -1) ** 2, axis=1) + 1e-20)
    loud = np.where(20 * np.log10(rms) > db)[0]
    return x[: (loud[-1] + 1) * SR] if loud.size else x


def _profile(x) -> dict:
    import audio_gate
    import numpy as np
    assert SR == 2 * audio_gate.SR
    y = np.ascontiguousarray(x.mean(1)[::2])
    # RMS -> -14 dBFS ~ итоговая громкость, иначе тишина -45 dB меряется не там
    return audio_gate.analyze_pcm(y * (10 ** (-14 / 20) / (np.sqrt(np.mean(y ** 2)) + 1e-9)))


def _tdiff(a: float, b: float) -> float:
    return abs((a - b + 0.5) % 1 - 0.5)


def _a2a(client, prompt: str, ref_path: str, sec: float, seed: int) -> str:
    from gradio_client import handle_file
    res = client.predict(
        audio_duration=float(sec), prompt=prompt, lyrics="[instrumental]",
        infer_step=INFER_STEPS, guidance_scale=15.0, scheduler_type="euler",
        cfg_type="apg", omega_scale=10.0, manual_seeds=str(seed),
        guidance_interval=0.5, guidance_interval_decay=0.0, min_guidance_scale=3.0,
        use_erg_tag=True, use_erg_lyric=False, use_erg_diffusion=True, oss_steps=None,
        guidance_scale_text=0.0, guidance_scale_lyric=0.0,
        audio2audio_enable=True, ref_audio_strength=A2A_STRENGTH,
        ref_audio_input=handle_file(ref_path), lora_name_or_path="none",
        api_name="/__call__",
    )
    return res[0]


def loudnorm_mp3(src, dst, lufs: float = TARGET_LUFS, tp: float = TARGET_TP) -> None:
    """Двухпроходный loudnorm (linear) -> mp3 320k. Однопроходный давал -12.6 LUFS / TP -0.9."""
    import json
    import subprocess
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src),
         "-af", f"loudnorm=I={lufs}:TP={tp}:LRA=11:print_format=json", "-f", "null", "-"],
        check=True, capture_output=True, text=True,
    ).stderr
    m = json.loads(err[err.rindex("{"): err.rindex("}") + 1])
    af = (f"loudnorm=I={lufs}:TP={tp}:LRA=11:linear=true:"
          f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']},"
          f"alimiter=limit={10 ** ((tp - 0.3) / 20):.4f}:level=disabled")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", af, "-ar", str(SR),
         "-c:a", "libmp3lame", "-b:a", "320k", str(dst)],
        check=True, capture_output=True,
    )


def generate_coherent(prompt: str, total_sec: int, seed: int, out_path,
                      client_cls=Client) -> dict:
    """Связный long-form трек: база text2music + audio2audio-вариации базы."""
    import tempfile
    import wave
    from pathlib import Path

    import numpy as np

    work = Path(tempfile.mkdtemp(prefix="coherent_"))
    url, token = ace_endpoint()
    client = client_cls(url, token=token)
    meta = {"seed": seed, "segments": 0, "rejected_candidates": 0}
    xf = XFADE_SEC * SR
    next_seed = seed

    def pick(gen, ref):
        """Лучший из CANDIDATES: (без тишины, звукоряд базы, ближе по строю).
        Тишина — жёсткий дисквалификатор (доминирует в лексикографическом
        score): допущенный кусок с -48 dB провалом дал fail гейта."""
        nonlocal next_seed
        best = None
        for _ in range(CANDIDATES):
            s, next_seed = next_seed, next_seed + 1
            x = _trim_tail_silence(_read(gen(s)))
            p = _profile(x)
            ref = ref or p
            score = (-p["silent_seconds"], p["signature"] == ref["signature"],
                     -_tdiff(p["tuning_median"], ref["tuning_median"]))
            if best is None or score > best[0]:
                best = (score, x, p)
            if not score[0] and score[1] and -score[2] <= TUNING_TOL:
                break
            meta["rejected_candidates"] += 1
        return best[1], best[2]

    first = min(CHUNK_SEC, total_sec)
    base, ref = pick(lambda s: generate_track(prompt, first, seed=s, client_cls=client_cls), None)
    meta.update(signature=ref["signature"], key=ref["key"], tuning=ref["tuning_median"])
    base_path = work / "base.wav"
    import audio_gate
    audio_gate.write_wav(base_path, base / (np.abs(base).max() + 1e-9) * 0.9, SR)
    segs = [base]
    meta["segments"] = 1
    total = lambda: sum(len(x) for x in segs) - xf * (len(segs) - 1)  # noqa: E731
    while total() < total_sec * SR:
        need = total_sec - total() / SR + XFADE_SEC + 2
        sec = max(30, min(CHUNK_SEC, need))
        new, _ = pick(lambda s: _a2a(client, prompt, str(base_path), sec, s), ref)
        if len(new) < 2 * xf:
            raise RuntimeError(f"audio2audio вернул слишком короткий кусок ({len(new) / SR:.1f}с)")
        segs.append(new)
        meta["segments"] += 1

    # громкость кусков выравниваем по RMS базы, иначе скачки на стыках
    rms = lambda x: float(np.sqrt(np.mean(x ** 2)) + 1e-9)  # noqa: E731
    segs = [segs[0]] + [x * (rms(segs[0]) / rms(x)) for x in segs[1:]]
    t = np.linspace(0, np.pi / 2, xf, dtype=np.float32)[:, None]
    out = [segs[0]]
    for x in segs[1:]:
        prev = out[-1]
        prev[-xf:] = prev[-xf:] * np.cos(t) + x[:xf] * np.sin(t)
        out.append(x[xf:])
    # обрезка до total_sec + фейд-аут
    over = sum(len(x) for x in out) - total_sec * SR
    while over > 0:
        cut = min(over, len(out[-1]))
        out[-1] = out[-1][: len(out[-1]) - cut]
        if not len(out[-1]):
            out.pop()
        over -= cut
    fade = min(len(out[-1]), 3 * SR)
    out[-1][-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
    peak = max(float(np.abs(x).max()) for x in out)
    raw = work / "raw.wav"
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        for x in out:
            w.writeframes((np.clip(x / max(peak, 1e-9) * 0.5, -1, 1) * 32767).astype("<i2").tobytes())
    loudnorm_mp3(raw, out_path)
    return meta


def main() -> None:
    import json

    run_dir = latest_run_dir()
    idea = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))
    mood = idea.get("mood", "cozy lofi")

    # Канал-эксперимент (DECISIONS.md п.8): сцена из idea.json -> промпт сцены
    if idea.get("channel") == "dd":
        import dd_channel

        scene_name = idea.get("scene")
        scene = next((s for s in dd_channel.load_scenes() if s["name"] == scene_name), None)
        if scene is None:
            raise SystemExit(f"dd scene not found: {scene_name!r}")
        genre_name, prompt = scene["name"], scene["music_prompt"]
    elif os.environ.get("GENRE"):
        # several videos/day, one per genre (workflow matrix sets GENRE)
        genre_name = os.environ["GENRE"]
        prompt = {**CANDIDATE_GENRE_PROMPTS, **GENRE_PROMPTS}[genre_name]
    else:
        genre_name, prompt = genre_for_mood(mood)

    # Длительность по умолчанию 60с (сигнатурный клип). Long-form
    # (sleep/meditation/ambient каналы по конкурентному анализу — часто
    # 1-3ч, см. DECISIONS.md п.5) запрашивается через TRACK_DURATION_SEC,
    # собирается generate_coherent(): база text2music + audio2audio-вариации.
    duration = int(os.environ.get("TRACK_DURATION_SEC", "60"))

    seed = abs(hash(run_dir.name)) % (2**31)

    out_path = run_dir / "track.mp3"
    coherent = generate_coherent(prompt, duration, seed=seed, out_path=out_path)
    (run_dir / "music_meta.json").write_text(
        json.dumps({"genre": genre_name, "prompt": prompt, "seed": seed, "duration": duration,
                    **coherent},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"track -> {out_path} (genre={genre_name}, {duration}s)")


if __name__ == "__main__":
    main()
