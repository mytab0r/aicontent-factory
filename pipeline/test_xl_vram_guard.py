#!/usr/bin/env python3
"""t_f3937fb8: XL на 12 ГБ — только контейнер ace_mode.sh xl (XL единственный DiT), без /v1/init и on-demand env.
Образ ace-step = upstream dce6214: ON_DEMAND_MODEL_LOAD нет, /v1/init XL поверх turbo+base = status=0 навсегда."""
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent.parent
wf = (root / ".github/workflows/xl-probe.yml").read_text()
music = (root / "pipeline/03_music.py").read_text()
mode = root / "deploy/gpu-pc/ace_mode.sh"

assert not re.search(r'post\(\s*"/v1/init"', music), "03_music: /v1/init на 12 ГБ запрещён"
code = "\n".join(l.split("#", 1)[0] for l in wf.splitlines())
assert "/v1/init" not in code and "ON_DEMAND" not in code, "xl-probe: ни /v1/init, ни on-demand env (нет в образе)"
xl = wf.index("ace_mode.sh xl")
assert xl < wf.index("gen xl_solo") < wf.index("ace_mode.sh prod") < wf.index("gen turbo_2"), "порядок фаз xl/prod"
assert wf.index("ace_mode.sh prod", wf.index("gen turbo_2")) > 0, "cleanup возвращает prod"
s = mode.read_text()
xl_branch = re.search(r"xl\)\s+P=acestep-v15-xl-sft; S=\"\"", s)
assert xl_branch, "xl-режим: XL-sft primary, без CONFIG_PATH2 (base) — иначе два DiT в 12 ГБ"
assert s.index("docker rm -f ace-step") < s.index("docker run -d --name ace-step"), "старый контейнер убрать ДО нового"
assert subprocess.run(["sh", "-n", str(mode)]).returncode == 0
r = subprocess.run(["sh", str(mode), "bogus"], capture_output=True, text=True)
assert r.returncode == 2 and "usage" in r.stdout, r
print("OK: XL VRAM guard")
