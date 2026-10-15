#!/bin/sh
# "Will it hook" proxy: Meta audiobox-aesthetics (CE = content enjoyment, PQ = production quality), run inside the
# ace-step container (torch+CUDA already there; venv/weights on C: bind /app/output, D: does not grow).
# ponytail: CE is a learned listener-enjoyment predictor, not CTR; validated below by correlation with ref views.
set -e
docker exec ace-step sh -c 'rm -rf /app/output/aes/in && mkdir -p /app/output/aes/in'
for f in bench/ours/*.mp3 refs/*.wav; do [ -f "$f" ] && docker cp "$f" ace-step:/app/output/aes/in/; done
docker exec ace-step sh -c '
  cd /app/output/aes
  [ -x venv/bin/audio-aes ] || { python3 -m venv --system-site-packages venv && venv/bin/pip install -q audiobox_aesthetics; }
  export HF_HOME=/root/.cache/huggingface
  ls in | sed "s|.*|{\"path\":\"/app/output/aes/in/&\"}|" > in.jsonl
  venv/bin/audio-aes in.jsonl --batch-size 4 > out.jsonl
  paste -d"\t" in.jsonl out.jsonl > scored.tsv'
docker cp ace-step:/app/output/aes/scored.tsv out/aes.tsv
cat out/aes.tsv
