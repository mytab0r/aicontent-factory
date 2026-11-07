"""Генерация D&D сэмплов с чекпоинтами: fail-fast на квоте + resume по файлам.

Решение (обсуждение 2026-10-03, владелец): старый oneoff-воркфлоу спал
раннер по 30 мин внутри retry-цикла до 10ч — дорого и хрупко. Новое
поведение: любой сбой (квота/сеть/ошибка API) = мгновенное падение рана,
успешные треки сохранены как артефакты (if-no-files-found: error +
always() на upload), повторный диспатч продолжает с места падения
(resume: готовые dd_*.mp3 не перегенерируются).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dd_channel
import importlib.util


class QuotaExhausted(Exception):
    """Дневная квота ZeroGPU исчерпана — ран должен упасть сразу."""


SCENES = dd_channel.load_scenes()
OUT_DIR = Path("samples_candidates")


def _load_music_module():
    """Загружает 03_music.py как модуль (generate_track_v15, _Http)."""
    mod_path = Path(__file__).resolve().parent / "03_music.py"
    spec = importlib.util.spec_from_file_location("music_mod", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def run_local_generation(scenes: list[dict], out_dir: Path, generate=None):
    """root-cause t_61f7c556: локальный ACE-Step 1.5, ноль ZeroGPU-квоты.

    generate_track_v15 из 03_music.py на ACE15_ENDPOINT (REST контейнера
    на ПК). Возвращает (сколько новых, ошибка|None) — fail-fast как run_batch.
    """
    music = _load_music_module()
    generate = generate or music.generate_track_v15
    endpoint = os.environ.get("ACE15_ENDPOINT")
    if not endpoint:
        return 0, "ACE15_ENDPOINT не задан (root-cause t_61f7c556: ZeroGPU-фолбэка нет)"
    api = music._Http(endpoint)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated = 0
    for i, scene in enumerate(pending_scenes(scenes, out_dir)):
        try:
            dest = out_dir / out_name(scene)
            generate(scene["music_prompt"], 45, i, dest, api=api)
            generated += 1
            print(f"saved {dest.name}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"FAILED {scene['name']}: {e}", flush=True)
            return generated, e
    return generated, None


def main() -> None:
    from gradio_client import Client

    endpoint = os.environ.get("ACE15_ENDPOINT")
    if endpoint:
        generated, err = run_local_generation(SCENES, OUT_DIR)
    else:
        print("ACE15_ENDPOINT не задан — фолбэк на HF Space (тарат квоту ZeroGPU; "
              "временный, root-cause t_61f7c556)", flush=True)
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
