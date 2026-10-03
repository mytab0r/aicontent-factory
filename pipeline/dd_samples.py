"""Генерация D&D сэмплов с чекпоинтами: fail-fast на квоте + resume по файлам.

Решение (обсуждение 2026-10-03, владелец): старый oneoff-воркфлоу спал
раннер по 30 мин внутри retry-цикла до 10ч — дорого и хрупко. Новое
поведение: любой сбой (квота/сеть/ошибка API) = мгновенное падение рана,
успешные треки сохранены как артефакты (if-no-files-found: error +
always() на upload), повторный диспатч продолжает с места падения
(resume: готовые dd_*.mp3 не перегенерируются).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dd_channel


class QuotaExhausted(Exception):
    """Дневная квота ZeroGPU исчерпана — ран должен упасть сразу."""


SCENES = dd_channel.load_scenes()
OUT_DIR = Path("samples_candidates")


def out_name(scene: dict) -> str:
    return f"dd_{scene['name'].replace(' ', '_')}.mp3"


def pending_scenes(scenes: list[dict], out_dir: Path) -> list[dict]:
    """Сцены без сохранённого mp3 (resume: готовое не трогаем)."""
    return [s for s in scenes if not (out_dir / out_name(s)).exists()]


def run_batch(scenes: list[dict], out_dir: Path, client_factory):
    """Генерит недостающие треки. Возвращает (сколько новых, ошибка|None).

    Fail-fast: на исчерпании квоты возвращает ошибку немедленно (без снов),
    уже сохранённые файлы остаются на месте — следующий ран их пропустит.
    Прочие исключения (сеть и т.п.) — тоже наружу: ран падает, state цел.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = pending_scenes(scenes, out_dir)
    generated = 0
    client = None
    for scene in todo:
        try:
            if client is None:
                client = client_factory()
            result = client.predict(
                audio_duration=45.0,
                prompt=scene["music_prompt"],
                lyrics="[instrumental]",
                infer_step=27,
                guidance_scale=15.0,
                scheduler_type="euler",
                cfg_type="apg",
                omega_scale=10.0,
                manual_seeds=None,
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
            dest = out_dir / out_name(scene)
            Path(result[0]).replace(dest)
            generated += 1
            print(f"saved {dest.name}", flush=True)
        except Exception as e:  # noqa: BLE001 — граница процесса, классифицируем
            if "quota" in str(e).lower():
                print(f"quota exhausted after {generated} new track(s) — fail fast", flush=True)
                return generated, QuotaExhausted(str(e))
            print(f"FAILED {scene['name']}: {e}", flush=True)
            return generated, e
    return generated, None


def main() -> None:
    import os

    from gradio_client import Client

    token = os.environ.get("HF_TOKEN") or None
    generated, err = run_batch(
        SCENES, OUT_DIR, client_factory=lambda: Client("ACE-Step/ACE-Step", token=token)
    )
    done = len(list(OUT_DIR.glob("dd_*.mp3")))
    print(f"progress: {done}/{len(SCENES)} total ({generated} new this run)")
    if err is not None:
        # неполный результат = падение рана: видно в CI, диспатч продолжит
        raise SystemExit(f"incomplete: {err}")
    print("all scenes generated")


if __name__ == "__main__":
    main()
