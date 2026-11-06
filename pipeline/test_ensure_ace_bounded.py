"""t_0c540f50: ensure_ace_step.sh must fail fast with ::error:: on a stuck `docker pull`, never hang to the step timeout.
Runs 39195973181/39201205845/39205125539 hung 60/280/280 min in an unbounded pull retry loop.
Run: python3 pipeline/test_ensure_ace_bounded.py"""
import os, re, signal, subprocess, tempfile, time, pathlib
SH = pathlib.Path(__file__).resolve().parent.parent / "deploy/gpu-pc/ensure_ace_step.sh"

def test_static_bounds():
    src = SH.read_text()
    assert not re.search(r"^(?!\s*#)(?!.*timeout).*docker pull", src, re.M), "docker pull without timeout"
    assert re.search(r"flock -w", src), "flock without -w (unbounded lock wait)"

def test_hung_pull_fails_fast():
    d = tempfile.mkdtemp()
    fake = os.path.join(d, "docker")
    open(fake, "w").write("""#!/bin/sh
case "$*" in
  "inspect ace-step"|"image inspect "*|"manifest inspect"*) exit 1 ;;
  pull*) exec sleep 1000 ;;
  run*) echo "Filesystem 1K-blocks Used Available"; echo "x 1 1 104857600" ;;
esac
exit 0
""")
    os.chmod(fake, 0o755)
    env = {**os.environ, "PATH": d + ":" + os.environ["PATH"], "ACE_PULL_BUDGET_S": "3",
           "ACE_LOCK": os.path.join(d, "lock"), "DISK_FREE_GB": "500"}
    t0 = time.time()
    p = subprocess.Popen(["sh", str(SH)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, start_new_session=True)
    try:
        out = p.communicate(timeout=90)[0]
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        raise AssertionError("ensure_ace_step.sh hangs on a stuck docker pull (t_0c540f50)")
    dt = time.time() - t0
    assert p.returncode != 0 and "::error::ace-step pull failed" in out, out
    assert dt < 60, (dt, out)
    return dt

if __name__ == "__main__":
    test_static_bounds(); dt = test_hung_pull_fails_fast(); print(f"ok: stuck pull -> ::error:: in {dt:.1f}s")
