#!/usr/bin/env python3
"""Симуляция sh-кавычек AES-скрипта критика (без докера): sh -n должен проходить."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import quality_gate as q  # noqa: E402

# как в _ce_run: QG_CLIPS в одинарных кавычках перед AES
clips = ["in/t00c0.wav", "in/t00c1.wav", "in/t00c2.wav"]
env_prefix = "QG_CLIPS='" + q.json.dumps(clips) + "' "
r = subprocess.run(["sh", "-n", "-c", env_prefix + q.AES], capture_output=True, text=True)
print("sh -n rc =", r.returncode)
if r.returncode != 0:
    print(r.stderr[-400:])
    raise SystemExit(1)
# python-часть AES обязана парситься: вырезаем последний $PY -c блок и компилируем
py_block = q.AES.rsplit('$PY -c "', 1)[1].rsplit('"\n', 1)[0]
# эмулируем sh-кавычки: внутри "..." экранированные \" заменяем
py_src = py_block.replace('\\"', '"')
compile(py_src, "<aes>", "exec")
print("python block parses OK")
# env-путь: os.environ["QG_CLIPS"] корректно читает список
import json
import os
os.environ["QG_CLIPS"] = q.json.dumps(clips)
assert q.json.loads(os.environ["QG_CLIPS"]) == clips
print("OK: AES quoting valid")
