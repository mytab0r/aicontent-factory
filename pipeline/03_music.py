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
# Стало: кусок 1 = text2music, дальше ACE-Step extend: в модель грузится
# хвост CONTEXT_SEC уже собранного трека, она дорисовывает EXT_SEC продолжения
# (repaint за правым краем — тот же материал, та же тональность/строй).
# На каждый extend до CANDIDATES seed'ов; берётся первый, чья новая часть
# совпала со звукорядом первого куска, строй в пределах TUNING_TOL и без
# тишины. Стык — equal-power crossfade XFADE_SEC внутри хвоста (оба сигнала
# там = один и тот же материал). Финал: loudnorm -14 LUFS / TP -1.5 (запас
# под mp3), фейд-аут. Гейт audio_gate.py проверяет результат перед publish.
FIRST_SEC = 120
CONTEXT_SEC = 30
EXT_SEC = 120  # CONTEXT_SEC + EXT_SEC <= 240: у ACE-Step extend баг на >240с окне
XFADE_SEC = 4
CANDIDATES = 3
TUNING_TOL = 0.075
SR = 44100


def _read(path) -> "np.ndarray":
    import subprocess
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, 2).copy()


def _write_wav(path, x) -> None:
    import audio_gate
    audio_gate.write_wav(path, x, SR)


def _trim_tail_silence(x, db: float = -40.0):
    """Срезает тихий хвост (модель гасит звук к концу куска) — иначе дыра на стыке."""
    import numpy as np
    sec = len(x) // SR
    rms = np.sqrt(np.mean(x[: sec * SR].reshape(sec, -1) ** 2, axis=1) + 1e-20)
    loud = np.where(20 * np.log10(rms) > db)[0]
    return x[: (loud[-1] + 1) * SR] if loud.size else x


def _tail(segs: list, n: int):
    import numpy as np
    out, have = [], 0
    for seg in reversed(segs):
        out.append(seg[-(n - have):])
        have += len(out[-1])
        if have >= n:
            break
    return np.concatenate(out[::-1])


def _profile(x) -> dict:
    import audio_gate
    import numpy as np
    assert SR == 2 * audio_gate.SR
    return audio_gate.analyze_pcm(np.ascontiguousarray(x.mean(1)[::2]))


def _tdiff(a: float, b: float) -> float:
    return abs((a - b + 0.5) % 1 - 0.5)


def _extend(client, prompt: str, src_path: str, ext_sec: float, seed: int) -> str:
    from gradio_client import handle_file
    res = client.predict(
        text2music_json_data=None,
        extend_input_params_json=None,
        extend_seeds=str(seed),
        left_extend_length=0.0,
        right_extend_length=float(ext_sec),
        extend_source="upload",
        extend_source_audio_upload=handle_file(src_path),
        prompt=prompt,
        lyrics="[instrumental]",
        infer_step=INFER_STEPS,
        guidance_scale=15.0,
        scheduler_type="euler",
        cfg_type="apg",
        omega_scale=10.0,
        manual_seeds=str(seed),
        guidance_interval=0.5,
        guidance_interval_decay=0.0,
        min_guidance_scale=3.0,
        use_erg_tag=True,
        use_erg_lyric=False,
        use_erg_diffusion=True,
        oss_steps=None,
        guidance_scale_text=0.0,
        guidance_scale_lyric=0.0,
        api_name="/extend_process_func",
    )
    return res[0]


def generate_coherent(prompt: str, total_sec: int, seed: int, out_path,
                      client_cls=Client) -> dict:
    """Связный long-form трек: text2music + цепочка extend + выбор кандидатов."""
    import subprocess
    import tempfile
    from pathlib import Path

    import numpy as np

    work = Path(tempfile.mkdtemp(prefix="coherent_"))
    url, token = ace_endpoint()
    client = client_cls(url, token=token)
    first = min(FIRST_SEC, total_sec)
    # ponytail: сегменты списком float32 (15 мин stereo = 300 МБ) — склейка
    # одним массивом не влезает в 1 ГБ контейнер; пишем wav потоково.
    segs = [_trim_tail_silence(_read(generate_track(prompt, first, seed=seed, client_cls=client_cls)))]
    ref = _profile(segs[0])
    meta = {"seed": seed, "segments": 1, "rejected_candidates": 0,
            "signature": ref["signature"], "key": ref["key"], "tuning": ref["tuning_median"]}
    total = lambda: sum(len(x) for x in segs)  # noqa: E731
    xf = XFADE_SEC * SR
    next_seed = seed + 1
    while total() < total_sec * SR:
        ctx = _tail(segs, CONTEXT_SEC * SR)
        src = work / f"ctx{meta['segments']}.wav"
        _write_wav(src, ctx)
        ext = max(15, min(EXT_SEC, total_sec - total() / SR + XFADE_SEC + 2))
        best = None
        for _ in range(CANDIDATES):
            s, next_seed = next_seed, next_seed + 1
            out = _read(_extend(client, prompt, str(src), ext, s))
            new = _trim_tail_silence(out[len(ctx) - xf:])
            del out
            prof = _profile(new[xf:]) if len(new) > xf + 15 * SR else ref
            score = (prof["signature"] == ref["signature"],
                     prof["silent_seconds"] == 0,
                     -_tdiff(prof["tuning_median"], ref["tuning_median"]))
            if best is None or score > best[0]:
                best = (score, new)
            if score[0] and score[1] and -score[2] <= TUNING_TOL:
                break
            meta["rejected_candidates"] += 1
        new = best[1]
        # equal-power crossfade: хвост пред. сегмента и голова нового — один материал
        last = segs[-1]
        if len(last) < xf or len(new) < 2 * xf:
            raise RuntimeError(f"extend вернул слишком короткий кусок ({len(new) / SR:.1f}с)")
        t = np.linspace(0, np.pi / 2, xf, dtype=np.float32)[:, None]
        last[-xf:] = last[-xf:] * np.cos(t) + new[:xf] * np.sin(t)
        segs.append(new[xf:])
        meta["segments"] += 1

    # обрезка до total_sec + фейд-аут
    over = total() - total_sec * SR
    while over > 0:
        cut = min(over, len(segs[-1]))
        segs[-1] = segs[-1][: len(segs[-1]) - cut]
        if not len(segs[-1]):
            segs.pop()
        over -= cut
    fade = min(len(segs[-1]), 3 * SR)
    segs[-1][-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
    peak = max(float(np.abs(x).max()) for x in segs)
    raw = work / "raw.wav"
    import wave
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        for x in segs:
            w.writeframes((np.clip(x / max(peak, 1e-9) * 0.5, -1, 1) * 32767).astype("<i2").tobytes())
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(raw),
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", str(SR),
         "-c:a", "libmp3lame", "-b:a", "320k", str(out_path)],
        check=True, capture_output=True,
    )
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
    # собирается generate_coherent(): text2music + цепочка extend.
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
