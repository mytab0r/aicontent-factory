#!/usr/bin/env python3
"""t_19928abd R1a: вечный генератор банка вместо крон-прогонов bank-fill.yml (бюджет 150 мин,
холостой старт раз в 2 ч). Один GPU-поток на жанр, сегмент за итерацию: bank.main(max_iter=1) =
выбор промпта (choose_prompt/pin_prompt/effective_target) -> ACE-Step -> полный гейт -> put_verified;
сегмент в банке до следующей генерации (чекпойнт). Выпуск (release_busy) = уступаем GPU и ждём.
Сбой ace-step/итерации = пауза и повтор, процесс не падает. SIGTERM = чистый выход (запись в банк
атомарна: .part + mv, обрыв не оставляет битого mp3).
Env как у bank-fill.yml: GENRE, BANK_TARGET=40, ACE15_ENDPOINT, ACE15_REF_AUDIO, ACE15_BESTOF=3,
ACE15_SEG_EXTRA=2, GITHUB_REPOSITORY + GH_TOKEN (для release_busy).
ponytail: эталон ref не скачивается (шаг bank-fill.yml): нет файла = noref; деплой (R1c) кладёт ref."""
import contextlib
import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bank  # noqa: E402

IDLE_S = 60  # выпуск идёт / ace-step не готов
FULL_S = 600  # банк полон или стоп по лимиту/полу диска
FAIL_S = 120  # итерация упала (выпуск рестартит ace-step, oneMKL и т.п.)
YIELD = HERE.parent / "deploy/gpu-pc/gpu_yield.sh"
LOCK = "/tmp/acf-bank-gpu.lock"


def ace_ready(sh=bank._sh) -> bool:
    """ace-step healthy. Остановлен/упал -> docker start (не restart: рестарт убил бы задачу выпуска)."""
    try:
        st = sh("docker", "inspect", "-f", "{{.State.Status}} {{.State.Health.Status}}", "ace-step").split()
    except Exception:
        return False
    if st and st[0] != "running":
        try:
            sh("docker", "start", "ace-step")
        except Exception:
            pass
        return False
    return st[-1:] == ["healthy"]


def gpu_yield(cmd):
    subprocess.run(["sh", str(YIELD), cmd])


@contextlib.contextmanager
def gpu_lock(path=LOCK):
    """Один GPU-поток на все жанры: воркеры lofi/phonk (R1c) генерируют по очереди, не параллельно."""
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def loop(once, busy, ready, stop, sleep=time.sleep, log=print, yield_=lambda c: None, lock=gpu_lock):
    """once() -> (в банке, цель). Выход только по stop(). Перед каждым сегментом под замком GPU
    останавливаем чужие GPU-контейнеры (идемпотентно); банк полон -> restore, VRAM отдан."""
    while not stop():
        if busy():
            log("воркер: выпуск в работе — жду")
            sleep(IDLE_S)
            continue
        if not ready():
            log("воркер: ace-step не healthy — жду")
            sleep(IDLE_S)
            continue
        try:
            with lock():
                if busy():  # пока ждали замок, мог стартовать выпуск
                    continue
                yield_("stop")  # 23.10: flint держал VRAM, VAE ушёл на CPU
                n, target = once()
        except Exception as e:  # SystemExit не ловим: SIGTERM = выход
            log(f"воркер: сбой {type(e).__name__}: {e} — повтор через {FAIL_S} с")
            sleep(FAIL_S)
            continue
        if n >= target:
            log(f"воркер: банк {n}/{target} — отдаю GPU, сплю {FULL_S} с")
            yield_("restore")
            sleep(FULL_S)


def main():
    st = {"stop": False}

    def term(*_):
        st["stop"] = True
        raise SystemExit(0)  # прерываем генерацию: в банк mp3 кладётся атомарно
    signal.signal(signal.SIGTERM, term)
    signal.signal(signal.SIGINT, term)
    for k, v in (("BANK_TARGET", "40"), ("ACE15_BESTOF", "3"), ("ACE15_SEG_EXTRA", "2")):
        os.environ.setdefault(k, v)
    os.environ.pop("BANK_DEADLINE_MIN", None)  # вечный: без дедлайна
    print(f"воркер банка {os.environ.get('GENRE', 'anime lofi')}: старт, цель {os.environ['BANK_TARGET']}",
          flush=True)
    try:
        loop(lambda: bank.main(max_iter=1), bank.release_busy, ace_ready, lambda: st["stop"])
    finally:
        gpu_yield("restore")
        print("воркер банка: остановлен", flush=True)


if __name__ == "__main__":
    main()