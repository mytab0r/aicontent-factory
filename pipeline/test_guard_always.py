"""P16: guard (один long-form жанра в сутки) обязан работать на ЛЮБОМ запуске daily-video, кроме явного force.
20.10: 4 ручных dispatch на master (01:30, 04:32, 06:38, 08:45) без scheduled=true шли мимо guard -> дубль long-form.
Запуск: python3 pipeline/test_guard_always.py [путь к workflow]"""
import pathlib, re, sys

WF = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml"


def guard_if(text):
    m = re.search(r"- name: guard[^\n]*\n(?:[ \t]+[^\n]*\n)*?[ \t]+if: ([^\n]+)", text)
    assert m, "шаг guard не найден"
    return m.group(1).strip()


def check(text):
    cond = guard_if(text)
    assert "schedule" not in cond and "inputs.scheduled" not in cond, f"guard только на schedule/scheduled: {cond}"
    assert "inputs.force" in cond, f"обход guard только через явный force: {cond}"
    assert re.search(r"\n      force:\n", text), "нет input force"
    assert "cancel-in-progress: false" in text, "concurrency должен сериализовать выпуски"


if __name__ == "__main__":
    old = """      - name: guard (один long-form жанра в сутки)\n        id: guard\n        if: github.event_name == 'schedule' || inputs.scheduled\n"""
    try:
        check(old)
        raise SystemExit("FAIL: старый guard (только schedule) должен падать")
    except AssertionError:
        pass
    check(WF.read_text(encoding="utf-8"))
    print("OK test_guard_always")
