#!/usr/bin/env python3
"""t_ba72c7aa R1: банк наполняется только прошедшими гейт сегментами и уступает GPU выпуску."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bank  # noqa: E402

WF = (Path(__file__).resolve().parent.parent / ".github/workflows/bank-fill.yml").read_text(encoding="utf-8")
Q = lambda *_: 0  # noqa: E731


def test_fill_stops_at_target_and_skips_rejects():
    put = []
    n = bank.fill(3, lambda: 1, lambda i: None if i == 0 else f"s{i}", put.append, lambda: False, log=Q)
    assert n == 3 and put == ["s1", "s2"], (n, put)


def test_fill_yields_to_release():
    calls = []
    n = bank.fill(9, lambda: 0, lambda i: calls.append(i) or "x", Q, lambda: True, log=Q)
    assert n == 0 and calls == []


def test_failure_during_release_is_yield_not_error():
    state = {"busy": False}

    def make(i):
        state["busy"] = True  # выпуск стартовал и рестартнул ace-step посреди задачи
        raise RuntimeError("timeout")
    assert bank.fill(5, lambda: 0, make, Q, lambda: state["busy"], log=Q) == 0


def test_failure_without_release_raises():
    def make(i):
        raise RuntimeError("timeout")
    try:
        bank.fill(5, lambda: 0, make, Q, lambda: False, log=Q)
    except RuntimeError:
        return
    raise AssertionError("сбой без выпуска должен ронять прогон")


def test_ace_hang_without_release_stops_clean():
    """run 39725738564: зависшая задача ACE -> ace_restart запрещён -> весь прогон упал (банк 15/30).
    Отказ рестарта = выйти чисто с сохранённым банком, не ронять прогон."""
    def make(i):
        if i == 1:
            raise bank.BankYield("ace-step завис, рестарт запрещён")
        return f"s{i}"
    put = []
    assert bank.fill(5, lambda: 0, make, put.append, lambda: False, log=Q) == 1 and put == ["s0"]


def test_workflow_never_restarts_gpu_and_no_artifacts():
    assert "docker restart" not in WF, "банк не рестартит ace-step: убьёт задачу выпуска"
    assert "upload-artifact" not in WF
    assert re.search(r"runs-on:\s*\[self-hosted, pc\]", WF)
    assert "group: daily-video" not in WF, "общая concurrency-группа с выпуском отменяет pending-выпуск"


def test_release_check_network_error_yields_not_crash():
    """run 39652298264: RemoteDisconnected в release_busy уронил банк. Сеть недоступна -> уступаем."""
    import http.client
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise http.client.RemoteDisconnected("Remote end closed connection without response")
    orig, bank.urllib.request.urlopen = bank.urllib.request.urlopen, boom
    try:
        assert bank.release_busy("o/r", "t", sleep=lambda s: None) is True
    finally:
        bank.urllib.request.urlopen = orig
    assert len(calls) >= 3, calls



def test_critic_on_release_start_is_clean_yield():
    """run 39800222017: выпуск стартовал -> scores() кинул RuntimeError, повторный busy() в fill
    вернул False (гонка статусов API) -> весь банк упал. Старт выпуска = BankYield, без гонки."""
    def busy():
        return True
    try:
        bank.guarded_scores(["a.mp3"], busy=busy, batch=lambda p: [7.0])
    except bank.BankYield:
        pass
    else:
        raise AssertionError("ожидался BankYield")
    assert bank.guarded_scores(["a"], busy=lambda: False, batch=lambda p: [7.0]) == [7.0]


def test_daily_state_commit_survives_parallel_matrix_conflict():
    """run 39800343057: две джобы матрицы правили .state/titles.json -> rebase CONFLICT -> выпуск failure.
    Push состояния = повтор с -X theirs (своя версия файла поверх), не падение."""
    dv = (Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")
    step = dv.split("name: commit mood rotation state", 1)[1].split("- name:", 1)[0]
    assert "pull --rebase -X theirs" in step and "|| true\n          git push\n" not in step, step


def test_generator_completes_largest_open_group():
    """run 39800343057: банк 22+ сегмента, но промпт генератора вращался по дню (89 F / 82 D / старые
    варианты) -> ни одной совместимой группы из 20 -> nobank, слот пропущен. Генератор добивает
    самую большую незакрытую группу, ротация дня — только когда открытых групп нет."""
    f, d = "x, 89 BPM, F major, y", "x, 82 BPM, D major, y"
    key = lambda p: (int(p.split(" BPM")[0].split()[-1]), p.split(", ")[2])  # noqa: E731
    assert bank.choose_prompt([f, d], {(89, "F major"): 12, (82, "D major"): 3}, 20, d, key) == f
    assert bank.choose_prompt([f, d], {(89, "F major"): 20, (82, "D major"): 3}, 20, f, key) == d
    assert bank.choose_prompt([f, d], {(89, "F major"): 20, (82, "D major"): 25}, 20, d, key) == d
    assert bank.choose_prompt([f, d], {}, 20, d, key) == d
    src = (Path(__file__).resolve().parent / "bank.py").read_text(encoding="utf-8")
    assert "choose_prompt(" in src.split("def main", 1)[1], "main() обязан выбирать промпт через choose_prompt"


def test_transient_failure_without_release_is_retried():
    """run 39884870081: одноразовый сбой критика (oneMKL: Cannot load libtorch_cpu.so, 0/21)
    на 39/40 уронил многочасовой прогон. Сбой без выпуска = повтор; падаем только после
    max_consecutive_fail сбоев подряд (устойчивая поломка всё ещё роняет прогон)."""
    fails = {"n": 0}
    seen = {}

    def make(i):
        if i == 2 and not seen.get(i):  # transient: один раз, повтор успешен
            seen[i] = True
            fails["n"] += 1
            raise RuntimeError("критик не отработал (0/21): oneMKL FATAL")
        return f"s{i}"

    put = []
    n = bank.fill(4, lambda: 0, make, put.append, lambda: False, log=Q)
    assert n == 4 and fails["n"] == 1, (n, fails)
    assert put == ["s0", "s1", "s2", "s3"], put


def test_persistent_failure_without_release_raises():
    calls = {"n": 0}

    def make(i):
        calls["n"] += 1
        raise RuntimeError("persistent breakage")

    try:
        bank.fill(5, lambda: 0, make, Q, lambda: False, log=Q)
    except RuntimeError:
        assert calls["n"] == 3, calls  # max_consecutive_fail по умолчанию
        return
    raise AssertionError("устойчивый сбой должен ронять прогон")


if __name__ == "__main__":
    test_release_check_network_error_yields_not_crash()
    test_fill_stops_at_target_and_skips_rejects()
    test_fill_yields_to_release()
    test_failure_during_release_is_yield_not_error()
    test_failure_without_release_raises()
    test_workflow_never_restarts_gpu_and_no_artifacts()
    test_ace_hang_without_release_stops_clean()
    test_critic_on_release_start_is_clean_yield()
    test_daily_state_commit_survives_parallel_matrix_conflict()
    test_generator_completes_largest_open_group()
    test_transient_failure_without_release_is_retried()
    test_persistent_failure_without_release_raises()
    print("ok test_bank")
