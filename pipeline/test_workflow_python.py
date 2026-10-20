"""P15: шаг workflow, вызывающий скрипт с не-stdlib импортами системным python3, = краш гейта/выпуска.
Каждый `python3 X.py` в workflows должен тянуть только stdlib (транзитивно по локальным модулям pipeline/)."""
import ast, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipeline"
CALL = re.compile(r"(?<![\w/.-])python3?\s+([\w./-]+\.py)")


def third_party(script, seen=None):
    seen = set() if seen is None else seen
    p = PIPE / pathlib.Path(script).name
    if p in seen or not p.exists():
        return set()
    seen.add(p)
    bad = set()
    for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
        mods = [a.name for a in n.names] if isinstance(n, ast.Import) else (
            [n.module] if isinstance(n, ast.ImportFrom) and n.module and not n.level else [])
        for m in mods:
            top = m.split(".")[0]
            if top in sys.stdlib_module_names:
                continue
            if (PIPE / f"{top}.py").exists():
                bad |= third_party(f"{top}.py", seen)
            else:
                bad.add(top)
    return bad


def violations(text):
    # модули, явно поставленные в этот же интерпретатор (`python3 -m pip install ...`), разрешены
    installed = {w for l in text.splitlines() if re.search(r"python3? -m pip install", l)
                 for w in re.split(r"[\s=<>]+", l.split("#")[0])}
    out = []
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        for s in CALL.findall(line):
            mods = third_party(s) - installed
            if mods:
                out.append((s, sorted(mods)))
    return out


def test_checker_catches_system_python_gate():
    assert violations("        run: python3 quality_gate.py --final")  # numpy без venv = RED


def test_explicit_install_ok():
    assert not violations("  python3 -m pip install -q numpy\n  python3 pipeline/loop_build.py final")


def test_venv_call_ok():
    assert not violations("        run: ../.venv/bin/python quality_gate.py")


def test_all_workflows_system_python_is_stdlib_only():
    bad = {}
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        v = violations(wf.read_text(encoding="utf-8"))
        if v:
            bad[wf.name] = v
    assert not bad, bad


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
    print("ok")
