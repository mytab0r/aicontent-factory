"""t_96de1cc6: в PR #271 закоммичен файл `-` (вывод `yes > -`). Мусор от shell-редиректов в корне репо = FAIL."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUNK = {"-", "--", "y", "nohup.out"}


def test_no_redirect_junk_tracked():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    bad = [f for f in files if Path(f).name in JUNK]
    assert not bad, f"мусорные файлы в репо: {bad}"


if __name__ == "__main__":
    test_no_redirect_junk_tracked()
    print("ok")
