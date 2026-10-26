"""P10: merge PR в master раньше зелёного required-check `test`.
GitHub Free: branch protection и rulesets недоступны (403 Upgrade required) —
гейт ставит merge-police: CI на push в master проверяет, что чек `test` HEAD-PR
завершился success ДО merge (+допуск SLACK_S на лаг API). Регрессия по классу
PR #88 / PR #205 (merged --auto при pending-проверках)."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
mp = importlib.import_module("merge_police")


def test_premature_when_test_finished_after_merge():
    # класс P10: merge 12:00, test завершился 12:05 — смержено до зелёного
    v = mp.evaluate("2026-10-25T12:00:00Z", "2026-10-25T12:05:00Z", "success")
    assert v["premature"] is True, v


def test_ok_when_test_green_before_merge():
    v = mp.evaluate("2026-10-25T12:00:00Z", "2026-10-25T11:58:00Z", "success")
    assert v["premature"] is False, v


def test_racing_within_slack_is_tolerated():
    # test завершился на 30 с позже merge — в пределах допуска, не тревожим
    v = mp.evaluate("2026-10-25T12:00:00Z", "2026-10-25T12:00:30Z", "success")
    assert v["premature"] is False, v


def test_failure_or_cancelled_check_is_premature():
    for concl in ("failure", "cancelled", "neutral", "skipped", None):
        v = mp.evaluate("2026-10-25T12:00:00Z", "2026-10-25T11:50:00Z", concl)
        assert v["premature"] is True, (concl, v)


def test_missing_test_check_run_is_premature():
    # merge без прогона test на HEAD (класс PR #88)
    v = mp.decide({"number": 1, "merged_at": "2026-10-25T12:00:00Z"},
                  [{"name": "other-check", "conclusion": "success", "completed_at": "2026-10-25T11:50:00Z"}])
    assert v["premature"] is True, v


def test_decide_passes_green_case():
    v = mp.decide({"number": 2, "merged_at": "2026-10-25T12:00:00Z"},
                  [{"name": "test", "conclusion": "success", "completed_at": "2026-10-25T11:55:00Z"}])
    assert v["premature"] is False, v


def test_ci_test_job_token_can_read_pulls_and_checks():
    # t_3ecce166: default read-токен = contents+metadata+packages -> merge-police 403, master ci красный,
    # pay-image не публиковал образ. Без этих прав P10 никогда не зелёный на push.
    import re
    from pathlib import Path
    wf = (Path(__file__).resolve().parent.parent / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    m = re.search(r"^  test:\n(.*?)(?=^  [a-z-]+:\n)", wf, re.M | re.S)
    assert m, "ci.yml: нет job test"
    for perm in ("pull-requests: read", "checks: read", "contents: read"):
        assert re.search(rf"^      {perm}\s*$", m.group(1), re.M), f"job test: нет permissions '{perm}' (merge-police 403)"


if __name__ == "__main__":  # t_110fa85f: CI запускает файл как скрипт
    _fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for _f in _fns:
        _f()
        print("ok", _f.__name__)
    print(f"PASS {len(_fns)} tests")
