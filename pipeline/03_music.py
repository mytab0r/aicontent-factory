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
GENRE_PROMPTS = {
    "anime lofi": (
        "anime lofi, soft rhodes piano melody, gentle boom bap drums with "
        "swing, warm bassline, vinyl noise, tape hiss, A minor, 82 BPM, "
        "instrumental, no vocals, cozy, nostalgic, study beats, Lofi Girl style"
    ),
    "jazzhop": (
        "nujabes style lofi hip hop, jazzy piano chords extended m7 maj9, "
        "boom bap swing drums, kick snare groove, warm upright bass, vinyl "
        "crackle, tape saturation, F minor, 78 BPM, instrumental, no vocals, "
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
        "C minor, 85 BPM, instrumental, no vocals, relaxed, smooth"
    ),
    "rainy night lofi": (
        "rainy night lofi, soft rhodes and muted guitar, slow swung drums, "
        "warm round bass, vinyl crackle, light rain ambience, G minor, "
        "75 BPM, instrumental, no vocals, introspective, cozy, late night"
    ),
}


def genre_for_mood(mood: str) -> tuple[str, str]:
    """Детерминированный выбор под-жанра по mood (воспроизводимо, но разнообразно)."""
    names = list(GENRE_PROMPTS.keys())
    idx = abs(hash(mood)) % len(names)
    name = names[idx]
    return name, GENRE_PROMPTS[name]


def generate_track(prompt: str, duration_sec: int, seed: int | None = None) -> str:
    """Вызывает ACE-Step, возвращает путь к сгенерированному mp3 (временный файл gradio)."""
    client = Client(SPACE)
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
        audio2audio_enable=False,
        ref_audio_strength=0.5,
        ref_audio_input=None,
        lora_name_or_path="none",
        api_name="/__call__",
    )
    return result[0]


def main() -> None:
    import json
    import shutil

    run_dir = latest_run_dir()
    idea = json.loads((run_dir / "idea.json").read_text(encoding="utf-8"))
    mood = idea.get("mood", "cozy lofi")

    duration = int(os.environ.get("TRACK_DURATION_SEC", "60"))
    # ACE-Step Space ограничивает длину одного вызова практичными рамками
    # (см. slider max=240s в API, но для стабильности очереди ZeroGPU
    # держим дефолт короче — 60с, видео повторно использует 04_assemble
    # без зацикливания аудио, если нужен более длинный ролик — увеличить
    # TRACK_DURATION_SEC, не меняя остальной пайплайн).

    genre_name, prompt = genre_for_mood(mood)
    seed = abs(hash(run_dir.name)) % (2**31)

    mp3_path = generate_track(prompt, duration_sec=duration, seed=seed)

    out_path = run_dir / "track.mp3"
    shutil.copy(mp3_path, out_path)
    (run_dir / "music_meta.json").write_text(
        json.dumps({"genre": genre_name, "prompt": prompt, "seed": seed, "duration": duration},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"track -> {out_path} (genre={genre_name}, {duration}s)")


if __name__ == "__main__":
    main()
