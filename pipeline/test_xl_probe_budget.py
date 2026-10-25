"""t_849a846a: шаг blind A/B в xl-probe.yml не может пережить свой timeout-minutes.

Прогоны 39071696001/39084115119/39095339812: воркер ace-step зомби (status=0 навсегда), каждый
вариант жёг свой timeout целиком, сумма > 150 мин -> GitHub убивал шаг. Тест выполняет настоящий
gen() из workflow в bash с заглушками (timeout/docker/sleep), худший случай: каждый вариант
съедает весь выданный таймаут + рестарт 18 мин. Итог обязан влезть в timeout-minutes шага.
"""
import os, pathlib, re, subprocess, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
STEP = "name: blind A/B"
RESTART = 72 * 15  # цикл ожидания healthy после рестарта ace-step


def _step(wf: str):
    s = wf[wf.index(STEP):]
    s = s[:s.index("\n      - name:", 1)]
    budget = int(re.search(r"timeout-minutes: (\d+)", s).group(1)) * 60
    lines = s.split("\n")
    a = next(i for i, l in enumerate(lines) if "STEP_END=" in l or l.strip().startswith("gen() {"))
    b = next(i for i in range(a, len(lines)) if lines[i] == "          }")
    return budget, "\n".join(l[10:] for l in lines[a:b + 1])


def worst_case_end(wf: str):
    budget, fn = _step(wf)
    with tempfile.TemporaryDirectory() as td:
        t = pathlib.Path(td)
        (t / "bin").mkdir(); (t / "xlrun").mkdir()
        for name, body in {"timeout": f'echo "$3" > {t}/to; exit 124',
                           "docker": "echo healthy", "sleep": "exit 0"}.items():
            f = t / "bin" / name; f.write_text("#!/bin/sh\n" + body + "\n"); f.chmod(0o755)
        fn = fn.replace("/tmp/xlrun", str(t / "xlrun"))
        drv = fn + f"""
for v in turbo_1:2700 xl_solo:1500 xl_1:2700 xl_2:2700 turbo_2:2700; do
  rm -f {t}/to; TO=${{v#*:}} gen ${{v%%:*}} X=1 >/dev/null 2>&1
  to=$(cat {t}/to 2>/dev/null || echo 0)
  [ "$to" -gt 0 ] && SECONDS=$((SECONDS + to + {RESTART}))
done
echo $SECONDS"""
        env = dict(os.environ, PATH=f"{t}/bin:" + os.environ["PATH"])
        out = subprocess.run(["bash", "-c", "set -o pipefail\n" + drv], cwd=td, env=env,
                             capture_output=True, text=True, check=True).stdout
        return budget, int(out.split()[-1])


def test_variants_fit_step_budget():
    budget, end = worst_case_end((ROOT / ".github/workflows/xl-probe.yml").read_text())
    assert end <= budget - 120, f"худший случай {end} с > бюджет шага {budget} с - 120 (сборка A/B)"


def test_have_pipeline_survives_set_e():
    """t_849a846a: HAVE=$(find ... | wc -l) без || echo 0 при set -e+pipefail убивал шаг
    мгновенно (каталог /tmp/xlrun отсутствует после rm -rf на свежем раннере, find rc=1),
    exit 1 без единой строки вывода. Строка обязана пережить отсутствие каталога."""
    wf = (ROOT / ".github/workflows/xl-probe.yml").read_text()
    line = next(l for l in wf.splitlines() if "HAVE=$(find /tmp/xlrun" in l)
    assert "|| echo 0" in line, f"HAVE-строка должна гасить rc=1 find: {line.strip()}"
    # поведенческая проверка того же класса: bash -e + pipefail, каталог не существует
    r = subprocess.run(["bash", "-c", "set -e\nset -o pipefail\n" + line.strip().lstrip() + "\necho alive $HAVE"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "alive" in r.stdout, f"rc={r.returncode} out={r.stdout!r} err={r.stderr!r}"


if __name__ == "__main__":
    test_variants_fit_step_budget(); test_have_pipeline_survives_set_e(); print("ok")
