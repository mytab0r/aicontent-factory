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
        if m and re.search(r"^def test_", s[m.end():], re.M):
            bad.append(f.name)
    return bad


def test_no_test_defined_after_main():
    assert dead_tests() == [], dead_tests()


if __name__ == "__main__":
    test_no_test_defined_after_main()
    print("ok test_no_test_defined_after_main")
