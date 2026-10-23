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


def test_target_grows_until_largest_group_has_margin():
    """run 39905560585: банк 40/40 (цель достигнута), но самая большая группа 21 (89 F), 2 сегмента
    битые -> 19 < 20 -> nobank, а генератор стоит: цель считалась по общему числу файлов.
    Цель растёт, пока в одной группе нет need+margin сегментов (запас на битые)."""
    c = {(92, "G major"): 12, (89, "F major"): 21, (82, "D major"): 6}
    assert bank.effective_target(40, 40, c, 20) == 43  # 21 -> 24: +3 (запас = need+MARGIN)
    assert bank.effective_target(40, 40, {(89, "F major"): 25}, 20) == 40  # 25 >= need+4: запас есть
    assert bank.effective_target(40, 10, {}, 20) == 40  # пустой банк: цель как была (>= 24)
    assert bank.effective_target(10, 30, {(1, "C major"): 5}, 20) == 49
    src = (Path(__file__).resolve().parent / "bank.py").read_text(encoding="utf-8").split("def main", 1)[1]
    assert "effective_target(" in src, "main() обязан пересчитывать цель через effective_target"
    assert "need + MARGIN" in src, "choose_prompt обязан добивать группу до need + MARGIN"
    assert ".mp3.part" in src and '"mv"' in src, "put: cp во временное имя + атомарный mv (обрыв прогона = нет битого .mp3)"



def test_hung_ace_restarts_when_no_release():
    """23.10: ace-step завис с 10:05 (VAE на CPU, VRAM держал flint), банк 5 прогонов выходил чисто
    без рестарта -> генератор стоял 4 ч. Рестарт запрещён только когда выпуск идёт/в очереди."""
    calls = []
    guard = bank.restart_guard(lambda: False, lambda *a, **k: calls.append(1))
    guard()
    assert calls == [1]
    guard = bank.restart_guard(lambda: True, lambda *a, **k: calls.append(2))
    try:
        guard()
    except bank.BankYield:
        assert calls == [1]
        return
    raise AssertionError("при выпуске рестарт обязан уступить")


def test_every_release_genre_has_bank_generator():
    """23.10: bank-fill наполнял только anime lofi (GENRE захардкожен) -> слоты chill phonk 22-23.10
    все nobank, генератора нет вообще. Каждый жанр матрицы daily-video обязан быть в матрице bank-fill."""
    dv = (Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")
    rel = set(re.findall(r'- genre:\s*"([^"]+)"', dv))
    gen = set(re.findall(r'- genre:\s*"([^"]+)"', WF))
    assert rel and rel <= gen, f"жанры без генератора банка: {rel - gen}"
    assert "GENRE: ${{ matrix.genre }}" in WF and "max-parallel: 1" in WF


def test_genre_without_bpm_gets_pinned_group():
    """Промпт phonk без BPM/тональности: bpm/key шли из seed каждого сегмента -> группа (None, None)
    смешивала темпы, переходы несовместимы. Генератор фиксирует пару в тексте промпта на прогон."""
    base = "chill phonk, instrumental"
    p = bank.pin_prompt(base, {}, 24, seed=5)
    assert p.startswith(base) and re.search(r", \d{2,3} BPM, [A-G] major$", p), p
    # открытая группа добивается, а не начинается новая
    counts = {(84, "G major"): 7, (None, None): 30, (80, "C major"): 24}
    assert bank.pin_prompt(base, counts, 24, seed=1) == base + ", 84 BPM, G major"
    # уже размеченный промпт (lofi ab_1/ab_3) не трогаем
    assert bank.pin_prompt("x, 89 BPM, F major", {}, 24, seed=1) == "x, 89 BPM, F major"


if __name__ == "__main__":
    test_every_release_genre_has_bank_generator()
    test_genre_without_bpm_gets_pinned_group()
    test_hung_ace_restarts_when_no_release()
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
    test_target_grows_until_largest_group_has_margin()
    print("ok test_bank")
