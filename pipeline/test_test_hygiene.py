#!/usr/bin/env python3
"""CI гоняет `python pipeline/test_X.py`: def test_ ниже блока if __name__ == "__main__" не выполняется
(19.10: test_trim_fade_tails был мёртв, trim_fade_tails в проде был no-op, стык R3 упал)."""
import re
from pathlib import Path


def dead_tests():
    bad = []
    for f in sorted(Path(__file__).resolve().parent.glob("test_*.py")):
        s = f.read_text(encoding="utf-8")
        m = re.search(r"^if __name__ == .__main__.:", s, re.M)
        # t_110fa85f: файл без блока __main__ тоже мёртв — CI гоняет `python test_X.py`,
        # def test_* без вызова не выполняются (тест t_bank_master так и не гонялся в CI).
        if re.search(r"^def test_", s, re.M) and (not m or re.search(r"^def test_", s[m.end():], re.M)):
            bad.append(f.name)
    return bad


def test_no_test_defined_after_main():
    assert dead_tests() == [], dead_tests()


def leaky_gate_calls():
    """t_110fa85f: негативные фикстуры через qg.main печатают `::error::quality gate: true peak … клиппинг`
    в лог CI; recurrence_scan принимает их за прод-клиппинг (CI 39699460380/39827389930). Вызов main без
    redirect_stdout в том же файле = утечка аннотаций."""
    me = Path(__file__).resolve()
    return [f.name for f in sorted(me.parent.glob("test_*.py"))
            if f != me and re.search(r"\b(qg|quality_gate)\.main\(", s := f.read_text(encoding="utf-8"))
            and "redirect_stdout" not in s]


def test_gate_main_output_captured():
    assert leaky_gate_calls() == [], leaky_gate_calls()


if __name__ == "__main__":
    test_no_test_defined_after_main()
    print("ok test_no_test_defined_after_main")
    test_gate_main_output_captured()
    print("ok test_gate_main_output_captured")
