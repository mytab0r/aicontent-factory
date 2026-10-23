"""t_14d314c2 regression: ensure ace-step must end fast with ::error::, never hang until the step timeout.
Runs 39195973181/39201205845/39205125539 hung 60/280/280 min in an unbounded `docker pull` retry loop.
Fake `docker` on PATH: pull hangs forever, HF relay fails. Script must exit != 0 with ::error:: in seconds.
Run: python3 deploy/gpu-pc/test_ensure_ace_step.py"""
import os, re, signal, subprocess, tempfile, time
here = os.path.dirname(os.path.abspath(__file__))
d = tempfile.mkdtemp()
open(os.path.join(d, "docker"), "w").write("""#!/bin/sh
case "$*" in
  "inspect ace-step"|"image inspect "*) exit 1 ;;
  pull*) exec sleep 1000 ;;
  "exec hermes-runner sh "*ace_relay.sh) echo "::error::fake relay down"; exit 1 ;;
  run*) echo "Filesystem 1G-blocks Used Available"; echo "x 100G 1G 99G" ;;
esac
exit 0
""")
os.chmod(os.path.join(d, "docker"), 0o755)
env = {**os.environ, "PATH": d + ":" + os.environ["PATH"], "ACE_PULL_BUDGET_S": "2", "ACE_LOCK": os.path.join(d, "lock")}
t0 = time.time()
p = subprocess.Popen(["sh", os.path.join(here, "ensure_ace_step.sh")], cwd=os.path.dirname(os.path.dirname(here)),
                     env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
try:
    out = p.communicate(timeout=60)[0]
except subprocess.TimeoutExpired:
    os.killpg(p.pid, signal.SIGKILL)
    raise AssertionError("ensure_ace_step.sh hangs on a stuck docker pull (t_14d314c2)")
dt = time.time() - t0
assert p.returncode != 0 and "::error::hf relay download failed" in out, out
assert "budget" in out and dt < 30, (dt, out)
# no unbounded waits may come back: every docker pull is under `timeout`, no sleep-polling loops
for f in ("ensure_ace_step.sh", "ace_relay.sh"):
    src = open(os.path.join(here, f)).read()
    assert not re.search(r"^(?!\s*#)(?!.*timeout).*docker pull", src, re.M), f + ": docker pull without timeout"
    assert not re.search(r"while[^\n]*\n(?:[^\n]*\n){0,3}?[^\n]*sleep", src), f + ": sleep-polling loop"
print(f"ok: hung pull + failed relay -> exit {p.returncode} with ::error:: in {dt:.1f}s")
