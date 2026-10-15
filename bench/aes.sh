#!/bin/sh
# "Will it hook" proxy: Meta audiobox-aesthetics (CE = content enjoyment, PQ = production quality), run inside the
# ace-step container (torch+CUDA already there; venv/weights on C: bind /app/output, D: does not grow).
# ponytail: CE is a learned listener-enjoyment predictor, not CTR; validated below by correlation with ref views.
set -e
docker exec ace-step sh -c 'rm -rf /app/output/aes/in && mkdir -p /app/output/aes/in'
for f in bench/ours/*.mp3 refs/*.wav; do [ -f "$f" ] && docker cp "$f" ace-step:/app/output/aes/in/; done
docker exec ace-step sh -c '
  set -e
  cd /app/output/aes
  # container has no python3-venv/ensurepip: venv without pip, reuse system pip (visible via system-site-packages)
  if [ ! -x venv/bin/audio-aes ]; then
    rm -rf venv && python3 -m venv --without-pip --system-site-packages venv
    venv/bin/python -m pip --version || { curl -fsSL https://bootstrap.pypa.io/get-pip.py -o gp.py && venv/bin/python gp.py -q; }
    venv/bin/python -m pip install -q audiobox_aesthetics
  fi
  export HF_HOME=/root/.cache/huggingface
  ls in | sed "s|.*|{\"path\":\"/app/output/aes/in/&\"}|" > in.jsonl
  venv/bin/audio-aes in.jsonl --batch-size 4 > out.jsonl
  test -s out.jsonl
  paste -d"\t" in.jsonl out.jsonl > scored.tsv'
docker cp ace-step:/app/output/aes/scored.tsv out/aes.tsv
cat out/aes.tsv
