#!/bin/sh
# "Will it hook" proxy: Meta audiobox-aesthetics CE/PQ, run inside ace-step (torch+CUDA there; pkgs on C: bind, D: ~0).
# ponytail: CE is a learned enjoyment predictor, not CTR; merge.py checks it against ref views.
set -e
docker exec ace-step sh -c 'rm -rf /app/output/aes/in && mkdir -p /app/output/aes/in'
for f in bench/ours/*.mp3 refs/*.wav; do [ -f "$f" ] && docker cp "$f" ace-step:/app/output/aes/in/; done
docker cp bench/aes_score.py ace-step:/app/output/aes/aes_score.py
docker exec ace-step sh -c '
  set -e; cd /app/output/aes; export HF_HOME=/root/.cache/huggingface PYTHONPATH=/app/output/aes/pkgs
  # torch lives in the image uv venv (/app/.venv), not system python3
  PY=python3; for c in /app/.venv/bin/python /opt/venv/bin/python; do [ -x $c ] && { PY=$c; break; }; done
  $PY -c "import torch" || { echo "no torch in $PY"; exit 1; }
  if ! $PY -c "import audiobox_aesthetics" 2>/dev/null; then
    if $PY -m pip --version >/dev/null 2>&1; then $PY -m pip install -q --no-deps --target pkgs audiobox_aesthetics
    elif command -v uv >/dev/null; then uv pip install -q --python $PY --no-deps --target pkgs audiobox_aesthetics
    else curl -sS https://bootstrap.pypa.io/get-pip.py -o gp.py && $PY gp.py -q --target pipboot && PYTHONPATH=pipboot $PY -m pip install -q --no-deps --target pkgs audiobox_aesthetics; fi
  fi
  # deps not in the ACE image, installed only if missing (torch/torchaudio come from the image)
  for m in submitit:submitit tqdm:tqdm huggingface_hub:huggingface_hub requests:requests safetensors:safetensors rich:rich; do $PY -c "import ${m%%:*}" 2>/dev/null || { $PY -m pip install -q --target pkgs ${m#*:} 2>/dev/null || uv pip install -q --python $PY --target pkgs ${m#*:} 2>/dev/null || PYTHONPATH=pipboot $PY -m pip install -q --target pkgs ${m#*:}; }; done
  $PY aes_score.py in > scored.tsv'
docker cp ace-step:/app/output/aes/scored.tsv out/aes.tsv
cat out/aes.tsv
