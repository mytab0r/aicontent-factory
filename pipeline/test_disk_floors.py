"""t_40bfcd35: единый источник порогов диска + запрет docker-томов для весов.
R1: пороги только в deploy/gpu-pc/disk_floors.env (D:40, C:30), скрипты читают оттуда.
R2: в workflows нет `-v <имя>:/` (named volume) для весов/кэшей/выходов — только bind на C:\\dockerlocal.
R3: disk_gate.sh отказывает с цифрами, если free - need < floor."""
import os, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPU = ROOT / "deploy/gpu-pc"
floors = dict(l.split("=", 1) for l in (GPU / "disk_floors.env").read_text().split("\n")
              if l and not l.startswith("#"))
assert floors["DISK_FLOOR_D_GB"] == "40" and floors["DISK_FLOOR_C_GB"] == "30", floors
print("floors D=40 C=30 OK")

# R1: никто кроме disk_floors.env не задаёт порог числом
for f in [*GPU.glob("*.sh"), *(ROOT / ".github/workflows").glob("*.yml")]:
    t = f.read_text(encoding="utf-8")
    assert not re.search(r"floor\w*=\$?\{?\w*:?-?\d", t, re.I), f"порог числом в {f.name}"
    assert not re.search(r"disk_gate\.sh\s+\d", t), f"старый вызов disk_gate.sh <GB> в {f.name}"
assert "disk_floors.env" in (GPU / "disk_gate.sh").read_text()
assert "disk_gate.sh" in (GPU / "ensure_ace_step.sh").read_text()
print("R1 single source OK")

# R3: гейт с цифрами (DISK_FREE_GB — подмена замера для теста)
def gate(drv, need, free):
    p = subprocess.run(["sh", str(GPU / "disk_gate.sh"), drv, str(need)], capture_output=True, text=True,
                       env={**os.environ, "DISK_FREE_GB": str(free)})
    return p.returncode, p.stdout + p.stderr
rc, out = gate("d", 10, 49); assert rc != 0 and "39" in out and "40" in out, out   # 49-10=39 < 40
rc, out = gate("d", 10, 50); assert rc == 0, out                                    # 50-10=40 >= 40
rc, out = gate("c", 20, 49); assert rc != 0 and "29" in out and "30" in out, out
rc, out = gate("c", 0, 30); assert rc == 0, out
rc, out = gate("x", 1, 99); assert rc != 0, out                                     # неизвестный диск = отказ
print("R3 gate refuses with numbers OK")

# R2: named volumes в workflows запрещены, кроме служебных (не веса): раннер, hermes-data,
# общий кеш action-архивов раннеров (~50 МБ tar.gz, t_77eb56b7)
ALLOW = re.compile(r"^(gh-runner-[\w-]+|hermes-data|gh-actions-archive-cache)$")
bad = []
for f in (ROOT / ".github/workflows").glob("*.yml"):
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        for name in re.findall(r"(?:-v|--volume)[ =]+([A-Za-z][\w.-]*):/", line):
            if not ALLOW.match(name):
                bad.append(f"{f.name}:{n}: -v {name}:/")
assert not bad, "docker-том для весов/данных запрещён, bind на C:\\dockerlocal:\n" + "\n".join(bad)
# сам детектор ловит пример
assert re.findall(r"(?:-v|--volume)[ =]+([A-Za-z][\w.-]*):/", "docker run -v minimax-weights:/w x") == ["minimax-weights"]
print("R2 no weight volumes OK")


# R4 (t_096e2d0d): замер без docker API ПК — host-df fallback; оба недоступны — fail-closed exit 2.
import tempfile
GATE = str(GPU / "disk_gate.sh")

def run_gate(need, **env):
    e = {k: v for k, v in os.environ.items() if k not in ("DISK_FREE_GB", "DISK_HOST_DF_PATHS")}
    e.update(env)
    p = subprocess.run(["sh", GATE, "d", str(need)], capture_output=True, text=True, env=e, timeout=120)
    return p.returncode, p.stdout + p.stderr

def fake_docker(body):
    d = tempfile.mkdtemp()
    f = Path(d) / "docker"
    f.write_text("#!/bin/sh\n" + body + "\n")
    f.chmod(0o755)
    return f"{d}:{os.environ['PATH']}"

# docker отдаёт цифру -> measure=docker (host-df не спрашивается)
rc, out = run_gate(1, PATH=fake_docker('echo "Filesystem 1024-blocks Used Available Use%"; echo "/x 1000 1 102400000 1%"'))
assert rc == 0 and "measure=docker" in out, out

# docker 401/недоступен (как в kanban-воркере на ПК) -> падаем на host-df, не падаем вообще
rc, out = run_gate(1, PATH=fake_docker('echo "401 Authorization Required" >&2; exit 1'),
                   DISK_HOST_DF_PATHS=tempfile.mkdtemp())
assert "measure=host-df:" in out and rc in (0, 1), out

# оба недоступны -> exit 2 и слово «отказ», а не «0G free» и не тихий проход
rc, out = run_gate(1, PATH=fake_docker('echo "401 Authorization Required" >&2; exit 1'), DISK_HOST_DF_PATHS="")
assert rc == 2 and "отказ" in out and "measure=" not in out, (rc, out)

# host-df на несуществующем пути не выдумывает цифру
rc, out = run_gate(1, PATH=fake_docker('exit 1'), DISK_HOST_DF_PATHS="/nonexistent/path/xyz")
assert rc == 2 and "отказ" in out, (rc, out)
print("R4 host-df fallback + fail-closed OK")
