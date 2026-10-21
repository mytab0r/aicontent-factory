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


if __name__ == "__main__":
    test_release_check_network_error_yields_not_crash()
    test_fill_stops_at_target_and_skips_rejects()
    test_fill_yields_to_release()
    test_failure_during_release_is_yield_not_error()
    test_failure_without_release_raises()
    test_workflow_never_restarts_gpu_and_no_artifacts()
    print("ok test_bank")
