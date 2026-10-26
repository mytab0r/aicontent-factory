"""t_265d0147: echo "...\" в run: — bash падал (unexpected EOF), continue-on-error это прятал. bash -n на каждом run:."""
import pathlib
import re
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def bad_runs(root=ROOT):
    out = []
    for wf in sorted((root / ".github/workflows").glob("*.y*ml")):
        for job in (yaml.safe_load(wf.read_text()) or {}).get("jobs", {}).values():
            for st in job.get("steps", []):
                if "run" not in st or st.get("shell", "bash").split()[0] not in ("bash", "sh"):
                    continue
                script = re.sub(r"\$\{\{.*?\}\}", "X", st["run"])
                r = subprocess.run(["bash", "-n"], input=script, capture_output=True, text=True, check=False)
                if r.returncode:
                    out.append(f"{wf.name}: {st.get('name')}: {r.stderr.strip()}")
    return out


def test_all_run_blocks_parse():
    assert bad_runs() == []


def test_catches_trailing_backslash_quote():
    r = subprocess.run(["bash", "-n"], input='echo "a\\b\\"\n', capture_output=True, text=True, check=False)
    assert r.returncode


if __name__ == "__main__":
    test_catches_trailing_backslash_quote()
    b = bad_runs()
    print("\n".join(b) or "ok")
    raise SystemExit(bool(b))
