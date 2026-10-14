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
import random

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


def generate_track(prompt: str, duration_sec: int, seed: int | None = None,
                   client_cls=Client, ref_audio: str | None = None) -> str:
    """Вызывает ACE-Step, возвращает путь к сгенерированному mp3 (временный файл gradio)."""
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
        infer_step=27,
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
        audio2audio_enable=bool(ref_audio),
        ref_audio_strength=0.5,
        ref_audio_input=ref_audio,
        lora_name_or_path="none",
        api_name="/__call__",
    )
    return result[0]


def chunk_plan(total_sec: int, max_chunk_sec: int = 240) -> list[int]:
    """Разбивает long-form длительность на куски <= max_chunk_sec для ACE-Step
    (один вызов практично ограничен ~240с, см. DECISIONS.md п.5). Короткий
    "сигнатурный" ролик (<= max_chunk_sec) не дробится -- один вызов, как раньше."""
    if total_sec <= max_chunk_sec:
        return [total_sec]
    n = -(-total_sec // max_chunk_sec)  # ceil div
    base = total_sec // n
    chunks = [base] * n
    chunks[-1] += total_sec - base * n  # остаток в последний кусок
    return chunks


def concat_tracks(paths: list[str], out_path) -> None:
    """Склеивает несколько mp3 в один файл через ffmpeg concat demuxer."""
    import subprocess
    import tempfile

    if len(paths) == 1:
        import shutil
        shutil.copy(paths[0], out_path)
        return
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in paths:
            f.write(f"file '{p}'\n")
        list_path = f.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, str(out_path)],  # куски ACE-Step не mp3: -c copy даёт exit 234,
            check=True, capture_output=True,
        )
    finally:
        os.unlink(list_path)


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
    # дробится chunk_plan() на вызовы ACE-Step <=240с и склеивается
    # concat_tracks() — пайплайн ниже этой строки не меняется.
    duration = int(os.environ.get("TRACK_DURATION_SEC", "60"))

    seed = abs(hash(run_dir.name)) % (2**31)

    # ротация эталона по дню (g1zm0_rotation); файла нет -> без эталона, выпуск не падает
    import datetime as _dt
    import g1zm0_rotation as rot
    ref_name = rot.pick_ref(_dt.date.today())
    ref_file = rot.REF_DIR / f"{ref_name}.wav"
    ref_audio = str(ref_file) if ref_file.exists() else None
    chunks = chunk_plan(duration)
    chunk_paths = [
        generate_track(prompt, duration_sec=c, seed=seed + i, ref_audio=ref_audio)
        for i, c in enumerate(chunks)
    ]

    out_path = run_dir / "track.mp3"
    concat_tracks(chunk_paths, out_path)
    (run_dir / "music_meta.json").write_text(
        json.dumps({"genre": genre_name, "prompt": prompt, "seed": seed, "duration": duration, "ref": ref_name if ref_audio else None},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"track -> {out_path} (genre={genre_name}, {duration}s)")


if __name__ == "__main__":
    main()
