#!/usr/bin/env python3
"""t_ba72c7aa R1: генератор банка сегментов. Музыка НЕ генерируется в слоте выпуска (владелец 21.10):
фоновый прогон кладёт в банк только сегменты, прошедшие гейт сегмента (тот же gated_gen, что в
03_music: best-of-3(+2), CE каждого окна >= MIN_CE, objective жанра). Банк = /app/output/bank/<жанр>
в контейнере ace-step (bind на C: dockerlocal/ace15/output, не D:). Выпуск = приоритет:
идёт/ждёт daily-video -> генератор уступает GPU и выходит; ace-step он НИКОГДА не рестартит
(рестарт убил бы задачу выпуска) — сбой задачи = выход, следующий прогон продолжит.
ponytail: сборка выпуска из банка = R2 (следующий PR); пока банк только наполняется."""
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
BANK_ROOT = "/app/output/bank"
CAP_FILES = 400  # ~4 МБ/сегмент -> ~1.6 ГБ, ниже лимита 15 ГБ спецификации


def slug(genre: str) -> str:
    return genre.replace(" ", "-")


def fill(target, have, make, put, busy, log=print, max_iter=40):
    """Наполнить банк до target. make(i) -> путь прошедшего гейт сегмента или None (брак).
    busy() = выпуск идёт/в очереди -> выход. Сбой генерации при занятом GPU = уступили, без ошибки."""
    n, i = have(), 0
    while n < min(target, CAP_FILES) and i < max_iter:
        if busy():
            log(f"банк: выпуск в работе — уступаю GPU (в банке {n})")
            break
        try:
            p = make(i)
        except Exception as e:
            if busy():
                log(f"банк: сбой {type(e).__name__} во время выпуска — выхожу (в банке {n})")
                break
            raise
        i += 1
        if p:
            put(p)
            n += 1
            log(f"банк: +1 сегмент, всего {n}/{target}")
    return n


def _sh(*a):
    return subprocess.run(list(a), check=True, capture_output=True, text=True).stdout


def release_busy(repo=None, token=None) -> bool:
    repo = repo or os.environ["GITHUB_REPOSITORY"]
    token = token or os.environ["GH_TOKEN"]
    for st in ("in_progress", "queued", "pending", "waiting"):
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/workflows/daily-video.yml/runs?status={st}&per_page=1",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            if json.load(r).get("total_count", 0):
                return True
    return False


def main():
    genre = os.environ.get("GENRE", "anime lofi")
    target = int(os.environ.get("BANK_TARGET", "30"))
    d = f"{BANK_ROOT}/{slug(genre)}"
    _sh("docker", "exec", "ace-step", "mkdir", "-p", d)

    def have():
        out = _sh("docker", "exec", "ace-step", "sh", "-c", f"ls {d} | grep -c mp3$ || true")
        return int(out.strip() or 0)

    spec = importlib.util.spec_from_file_location("music_bank", HERE / "03_music.py")
    music = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(music)

    def no_restart(*a, **k):
        raise RuntimeError("банк не рестартит ace-step (приоритет выпуска)")
    music.ace_restart = no_restart

    from quality_gate import ce_windows_batch, objective
    prompt, ref = music.GENRE_PROMPTS[genre], os.environ.get("ACE15_REF_AUDIO") or None
    try:
        import refpool
        pair = refpool.pick()
        prompt = pair["prompt"]
        refpool.ensure_ref(pair)
        ref = pair["ref_path"]
    except Exception as e:  # как в 03_music: эталон дня недоступен -> ref1
        print(f"refpool: {type(e).__name__}: {e}; fallback ref1")
    if ref and not Path(ref).is_file():
        ref = None
    run_dir = Path(tempfile.mkdtemp(prefix="bank_"))
    seed = random.randrange(2**31)
    def scores(paths):
        # критик чистит общий /app/output/qg в ace-step: при выпуске он чужой -> не запускаем
        if release_busy():
            raise RuntimeError("выпуск стартовал — критик банка не запускаю")
        return ce_windows_batch(paths)

    gen = music.gated_gen(music.mix_raw(run_dir, prompt, seed, ref, genre),
                          scores, lambda p: objective(p, genre)[0], attempts=3, extra=2)

    def put(p):
        name = f"{int(time.time())}_{seed}_{Path(p).stem}"
        meta = run_dir / f"{name}.json"
        meta.write_text(json.dumps({"genre": genre, "prompt": prompt, "ref": ref, "seed": seed,
                                    "src": Path(p).name, "ts": int(time.time())}, ensure_ascii=False))
        _sh("docker", "cp", str(meta), f"ace-step:{d}/{name}.json")
        _sh("docker", "cp", str(p), f"ace-step:{d}/{name}.mp3")  # mp3 последним: есть mp3 = есть meta
        Path(p).unlink(missing_ok=True)

    n = fill(target, have, gen, put, release_busy)
    print(f"банк {genre}: {n} сегментов (цель {target})")


if __name__ == "__main__":
    main()
