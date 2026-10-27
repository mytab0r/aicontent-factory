"""P23: выпуск 23.10 09:29 упал на install deps: таймаут PyPI, кэш uv в _temp (стирается каждый прогон).
Шаги установки в daily-video/bank-fill: постоянный кэш uv + ретраи, один сбой сети не снимает слот."""
import pathlib, re

WF = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"


def problems(text):
    out = []
    for m in re.finditer(r"uses: astral-sh/setup-uv@\S+\n((?:[ \t]+(?!- ).*\n)*)", text):
        if "cache-local-path:" not in m.group(1):
            out.append("setup-uv без постоянного cache-local-path")
    for line in text.splitlines():
        s = line.split("#")[0]
        if "uv pip install" in s and not re.search(r"for i in .*;\s*do .*uv pip install.*&& break", s):
            out.append("uv pip install без ретрая: " + s.strip())
    if "UV_HTTP_TIMEOUT" not in text:
        out.append("нет UV_HTTP_TIMEOUT")
    return out


def test_old_install_step_is_red():
    old = "      - uses: astral-sh/setup-uv@v3\n      - name: deps\n        run: |\n          uv pip install --python .venv/bin/python numpy\n"
    assert len(problems(old)) == 3


def test_release_and_bank_install_are_resilient():
    for name in ("daily-video.yml", "bank-fill.yml"):
        assert problems((WF / name).read_text(encoding="utf-8")) == [], name


def uv_without_setup(text):
    """t_1f53095a: bank-reserve run 40554433809 — `uv: command not found` на release-раннере (uv не в PATH
    без setup-uv). Любой workflow, зовущий uv, обязан ставить его через setup-uv."""
    calls = re.search(r"(?m)^[^#\n]*(?:^|[\s;&|(])uv (?:venv|pip|run|sync)\b", text)
    return bool(calls) and "astral-sh/setup-uv@" not in text


def test_uv_without_setup_is_red():
    assert uv_without_setup("    steps:\n      - run: |\n          uv venv .venv\n")
    assert not uv_without_setup("      - uses: astral-sh/setup-uv@v3\n      - run: uv venv .venv\n")


def test_all_workflows_calling_uv_install_it():
    bad = [p.name for p in sorted(WF.glob("*.yml")) if uv_without_setup(p.read_text(encoding="utf-8"))]
    assert bad == [], bad


if __name__ == "__main__":
    test_old_install_step_is_red(); test_release_and_bank_install_are_resilient()
    test_uv_without_setup_is_red(); test_all_workflows_calling_uv_install_it(); print("ok")
