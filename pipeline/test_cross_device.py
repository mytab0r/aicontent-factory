"""Регресс run 39450050733: tempfile в /tmp + os.replace в runs/ = OSError 18 (cross-device) после 2 ч GPU.
Класс: временный файл для os.replace должен лежать рядом с целью, не в tempfile-каталоге."""
import pathlib
import re


def test_no_tempfile_before_os_replace():
    bad = []
    for f in pathlib.Path(__file__).parent.glob("*.py"):
        if f.name.startswith("test_"):
            continue
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"(\w+)\s*=\s*tempfile\.(mktemp|mkstemp|NamedTemporaryFile)", src):
            if re.search(rf"os\.replace\(\s*{m.group(1)}\b", src[m.end():m.end() + 2000]):
                bad.append(f"{f.name}:{src[:m.start()].count(chr(10)) + 1}")
    assert not bad, f"tempfile + os.replace (cross-device): {bad}"
