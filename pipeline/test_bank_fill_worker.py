#!/usr/bin/env python3
"""t_19928abd R1a: вечный воркер банка — уступает выпуску, переживает сбои, сегмент за итерацию,
SIGTERM = чистый выход."""
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bank_fill_worker as w  # noqa: E402

Q = lambda *_: None  # noqa: E731
LOCK = os.path.join(tempfile.mkdtemp(), "gpu.lock")


def run(steps, busy, ready=lambda: True):
    """steps: список исходов once() (кортеж или исключение); стоп, когда кончились."""
    it, calls, ys = iter(steps), [], []
    st = {"left": len(steps)}

    def once():
        st["left"] -= 1
        r = next(it)
        calls.append(r)
        if isinstance(r, Exception):
            raise r
        return r
    sleeps = []
    w.loop(once, busy, ready, lambda: st["left"] <= 0, sleep=sleeps.append, log=Q, yield_=ys.append,
           lock=lambda: w.gpu_lock(LOCK))
    return calls, sleeps, ys


def test_survives_failures_and_checkpoints_each_segment():
    calls, sleeps, ys = run([RuntimeError("ace down"), (1, 40), (2, 40), (40, 40)], lambda: False)
    assert len(calls) == 4, calls  # сбой не роняет воркер
    assert sleeps == [w.FAIL_S, w.FULL_S], sleeps
    assert ys == ["stop"] * 4 + ["restore"], ys  # перед каждым сегментом — stop; полон -> restore


def test_yields_to_release_and_unhealthy_ace():
    b = iter([True, False, False, False])
    r = iter([False, True])
    calls, sleeps, _ = run([(1, 40)], lambda: next(b), lambda: next(r))
    assert calls == [(1, 40)] and sleeps == [w.IDLE_S, w.IDLE_S], (calls, sleeps)


def test_bank_main_is_single_segment_and_uses_worker_busy():
    src = (HERE / "bank.py").read_text(encoding="utf-8").split("def main", 1)[1]
    assert "max_iter=max_iter" in src and "restart_guard(busy" in src and "guarded_scores(paths, busy" in src
    assert "return n, target" in src
    ws = (HERE / "bank_fill_worker.py").read_text(encoding="utf-8")
    assert "bank.main(max_iter=1)" in ws and "docker\", \"restart" not in ws


def test_single_gpu_stream_across_workers():
    """R1c ставит 2 воркера (lofi, phonk) на один GPU: генерация строго по очереди."""
    active, peak = [0], [0]

    def seg():
        with w.gpu_lock(LOCK):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.2)
            active[0] -= 1
    ts = [threading.Thread(target=seg) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak[0] == 1, peak


def test_ace_ready_starts_stopped_never_restarts():
    seen = []

    def sh(*a):
        seen.append(a)
        return "exited " if a[1] == "inspect" else ""
    assert w.ace_ready(sh) is False and seen[-1] == ("docker", "start", "ace-step")
    assert w.ace_ready(lambda *a: "running healthy") is True
    assert w.ace_ready(lambda *a: "running starting") is False


def test_sigterm_exits_cleanly():
    code = ("import sys,time;sys.path.insert(0,%r);import bank_fill_worker as w;"
            "w.gpu_yield=lambda c:None;"
            "w.bank.release_busy=lambda:True;w.IDLE_S=0.05;w.main()") % str(HERE)
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    time.sleep(1.5)
    assert p.poll() is None, "воркер обязан работать бесконечно"
    p.send_signal(signal.SIGTERM)
    out, _ = p.communicate(timeout=10)
    assert p.returncode == 0 and "остановлен" in out, (p.returncode, out)


if __name__ == "__main__":
    test_survives_failures_and_checkpoints_each_segment()
    test_yields_to_release_and_unhealthy_ace()
    test_bank_main_is_single_segment_and_uses_worker_busy()
    test_single_gpu_stream_across_workers()
    test_ace_ready_starts_stopped_never_restarts()
    test_sigterm_exits_cleanly()
    print("ok test_bank_fill_worker")