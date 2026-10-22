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


class BankYield(Exception):
    """ace-step завис, а рестарт банку запрещён: выйти чисто, банк сохранён, следующий прогон продолжит."""


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
        except BankYield as e:
            log(f"банк: {e} — выхожу чисто (в банке {n})")
            break
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


def release_busy(repo=None, token=None, sleep=time.sleep, tries=3) -> bool:
    """Идёт/ждёт ли daily-video. Сеть к GitHub API недоступна после повторов -> True (уступаем GPU,
    следующий прогон продолжит): падение банка из-за RemoteDisconnected — не ошибка генерации."""
    repo = repo or os.environ["GITHUB_REPOSITORY"]
    token = token or os.environ["GH_TOKEN"]
    for st in ("in_progress", "queued", "pending", "waiting"):
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/workflows/daily-video.yml/runs?status={st}&per_page=1",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        for k in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    if json.load(r).get("total_count", 0):
                        return True
                break
            except OSError as e:  # URLError/RemoteDisconnected/timeout
                print(f"банк: проверка выпуска {type(e).__name__}, попытка {k + 1}/{tries}")
                sleep(10 * (k + 1))
        else:
            return True
    return False


def guarded_scores(paths, busy, batch):
    """Критик чистит общий /app/output/qg в ace-step: при выпуске он чужой -> не запускаем.
    Старт выпуска = чистый выход (BankYield), не RuntimeError: повторный busy() в fill мог
    вернуть False из-за гонки статусов API и уронить весь банк (run 39800222017)."""
    if busy():
        raise BankYield("выпуск стартовал — критик банка не запускаю")
    return batch(paths)


def stats_record(genre: str, prompt: str, seed: int, ok: bool, why: str = "", docker_sh=None) -> None:
    """t_ba72c7aa R4: статистика отказов по промптам/сидам в stats.jsonl рядом с банком."""
    import json as _json
    import time as _time
    row = _json.dumps({"prompt": prompt, "seed": seed, "ok": bool(ok), "why": why,
                       "ts": int(_time.time())}, ensure_ascii=False).replace("'", "'\''")
    d = f"{BANK_ROOT}/{slug(genre)}"
    cmd = f"echo '{row}' >> {d}/stats.jsonl"
    if docker_sh is not None:
        docker_sh("exec", "ace-step", "sh", "-c", cmd)
    else:
        _sh("docker", "exec", "ace-step", "sh", "-c", cmd)


def _stats_rows(lines):
    for x in lines:
        try:
            r = json.loads(x)
            if isinstance(r, dict):
                yield r
        except Exception:
            continue


def fail_rate(stats_lines: list, prompt: str, window: int = 20):
    """Доля брака среди последних window записей промпта; None = данных нет."""
    rows = [r for r in _stats_rows(stats_lines) if r.get("prompt") == prompt][-window:]
    if not rows:
        return None
    return sum(1 for r in rows if not r.get("ok")) / len(rows)


def prompt_enabled(stats_lines: list, prompt: str, window: int = 20, max_fail: float = 0.5,
                   min_n: int = 6) -> bool:
    """R4: доля брака > max_fail на окне = промпт выключен; мало данных = включен."""
    rows = [r for r in _stats_rows(stats_lines) if r.get("prompt") == prompt][-window:]
    if len(rows) < min_n:
        return True
    return fail_rate(stats_lines, prompt, window) <= max_fail


def pick_prompt(enabled=lambda lines, p: True) -> str:
    """R4: выбор промпта генерации: первый включённый из вариантов дня; все выключены ->
    fallback на pick() без фильтра (генерация не останавливается)."""
    import refpool
    pair = refpool.pick()
    lines = []
    d = f"{BANK_ROOT}/{slug(os.environ.get('GENRE', 'anime lofi'))}"
    try:
        lines = _sh("docker", "exec", "ace-step", "sh", "-c",
                    f"cat {d}/stats.jsonl 2>/dev/null || true").splitlines()
    except Exception:
        pass
    if not enabled(lines, pair["prompt"]):
        start = refpool.PROMPT_VARIANTS.index(pair["prompt"]) if pair["prompt"] in refpool.PROMPT_VARIANTS else 0
        for k in range(1, len(refpool.PROMPT_VARIANTS)):
            cand = refpool.PROMPT_VARIANTS[(start + k) % len(refpool.PROMPT_VARIANTS)]
            if enabled(lines, cand):
                print(f"bank: промпт дня выключен статистикой брака, беру вариант {k}")
                return cand
        print("bank: все варианты выключены статистикой — fallback промпт дня без фильтра")
    return pair["prompt"]


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
        raise BankYield("ace-step не ответил, рестарт банку запрещён (приоритет выпуска)")
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
        return guarded_scores(paths, release_busy, ce_windows_batch)

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
