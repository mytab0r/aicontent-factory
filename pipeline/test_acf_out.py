"""t_265d0147: acf_out.sh — медиа прогона на C:\\dockerlocal\\acf-out\\<run_id>\\ вместо GitHub artifacts.
put/get/keep, ретеншн 7 дней (кроме keep), лимит 20 ГБ (старейшие не-keep), пол C: из disk_gate.sh."""
import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SH = ROOT / "deploy/gpu-pc/acf_out.sh"
assert "20 * 1048576" in SH.read_text() and "604800" in SH.read_text(), "лимит 20 ГБ / 7 дней"
assert "disk_gate.sh\" c" in SH.read_text(), "пол C: только через disk_gate.sh (t_40bfcd35)"


def run(*a, free=500, cap=None, cwd=None):
    env = {**os.environ, "ACF_OUT_ROOT": str(store), "DISK_FREE_GB": str(free)}
    if cap:
        env["ACF_OUT_CAP_KB"] = str(cap)
    return subprocess.run(["sh", str(SH), *a], check=False, capture_output=True, text=True, env=env, cwd=cwd)


with tempfile.TemporaryDirectory() as t:
    t = Path(t); store = t / "store"; work = t / "w"; (work / "runs/x").mkdir(parents=True)
    (work / "runs/x/video.mp4").write_bytes(b"v" * 4096)
    r = run("put", "111", "runs/x/video.mp4", "runs/*/nope.mp4", cwd=work)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (store / "111/runs/x/video.mp4").read_bytes() == b"v" * 4096
    r = run("get", "111", str(t / "got"))
    assert r.returncode == 0 and (t / "got/runs/x/video.mp4").exists(), r.stderr
    print("put/get OK")

    # пол C: (disk_floors.env 30 ГБ): free 30 - need 1 = 29 < 30 -> отказ, ничего не записано
    r = run("put", "222", "runs/x/video.mp4", free=30, cwd=work)
    assert r.returncode != 0 and "30" in r.stdout and not (store / "222").exists(), r.stdout
    print("disk floor OK")

    # 7 дней: старый удаляется, старый keep остаётся
    for n in ("old", "oldkeep"):
        (store / n).mkdir(); (store / n / "f").write_bytes(b"x")
    run("keep", "oldkeep")
    old = time.time() - 8 * 86400
    for n in ("old", "oldkeep"):
        os.utime(store / n, (old, old))
    assert run("put", "333", "runs/x/video.mp4", cwd=work).returncode == 0
    assert not (store / "old").exists() and (store / "oldkeep/keep").exists() and (store / "333").exists()
    print("retention 7d + keep OK")

    # лимит: при переполнении удаляются старейшие не-keep, keep — нет
    for i, n in enumerate(("111", "333")):
        os.utime(store / n, (time.time() - 3600 + i, time.time() - 3600 + i))
    r = run("put", "444", "runs/x/video.mp4", cap=26, cwd=work)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (store / "111").exists() and (store / "oldkeep").exists() and (store / "444").exists(), os.listdir(store)
    r = run("put", "555", "runs/x/video.mp4", cap=1, cwd=work)
    assert r.returncode != 0 and (store / "oldkeep").exists(), "keep не удаляется даже при лимите"
    print("cap + keep OK")

    assert run("put", "../evil", "runs/x/video.mp4", cwd=work).returncode == 2
    print("run_id validation OK")
