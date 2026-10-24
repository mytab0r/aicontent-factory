#!/bin/sh
# Idempotent: ace-step (ACE-Step 1.5 REST :8001, comfynet) exists, running, healthy.
# Self-heal for "No such container"/missing image (t_03efb867, 19.10). Pull gated by disk_gate.sh (t_40bfcd35).
# Owner rules 19.10: R1 one pull at a time (caller holds concurrency lock + flock here);
# R2 retries = same docker pull, finished layers reused, no rmi/prune between attempts;
# R3 final failure -> drop only stale containerd ingest (partial blobs), D: before/after;
# R4 success -> no second copy (dangling / other ace-step tags) left.
set -eu
IMG=ghcr.io/ace-step/ace-step-1.5:latest
REPO=${IMG%:*}
A=/run/desktop/mnt/host/c/dockerlocal/ace15
INGEST=/var/lib/desktop-containerd/daemon/io.containerd.content.v1.content/ingest
dfree() { echo "D: free $(docker run --rm -v /run/desktop/mnt/host/d:/d:ro alpine:3.20 df -BG /d | awk 'NR==2{print $4}') [$1]"; }
host() { docker run --rm --privileged --pid=host alpine:3.20 nsenter -t 1 -m -- sh -c "$1"; }

exec 9>/tmp/ensure_ace_step.lock; flock 9   # R1 within this runner
dfree start
if docker inspect ace-step >/dev/null 2>&1; then
  [ "${1:-}" = restart ] && docker restart ace-step >/dev/null || docker start ace-step >/dev/null 2>&1 || true
else
  echo "ace-step missing -> recreate"
  if ! docker image inspect "$IMG" >/dev/null 2>&1; then
    # R3 t_40bfcd35: образ ложится в vhdx на D:. Размер = сжатые слои x2 (распаковка);
    # ponytail: оценка, не точный размер; при недоступном манифесте берём 25G (ace-step 1.5 ~ 20G).
    gb=$(docker manifest inspect -v "$IMG" 2>/dev/null | python3 -c "import json,sys;d=json.load(sys.stdin);d=d if isinstance(d,list) else [d];print(int(sum(l['size'] for m in d[:1] for l in m['OCIManifest' if 'OCIManifest' in m else 'SchemaV2Manifest']['layers'])*2/1e9)+1)" 2>/dev/null || echo 25)
    sh "$(dirname "$0")/disk_gate.sh" d "$gb"
    ok=0
    for i in 1 2 3 4 5 6 7 8; do
      # R2: plain pull resumes; log only layer outcome lines
      if docker pull "$IMG" 2>&1 | tee /tmp/pull.log | grep -E 'Already exists|Pull complete|Digest|Status|rror'; then :; fi
      echo "attempt $i: layers already-present=$(grep -c 'Already exists' /tmp/pull.log || true) completed=$(grep -c 'Pull complete' /tmp/pull.log || true)"
      dfree "after pull attempt $i"
      docker image inspect "$IMG" >/dev/null 2>&1 && { ok=1; break; }
      sleep 20
    done
    if [ $ok = 0 ]; then
      dfree "before ingest cleanup"
      host "du -sh $INGEST 2>/dev/null; find $INGEST -mindepth 1 -maxdepth 1 -type d -mmin +10 -exec rm -rf {} +; du -sh $INGEST 2>/dev/null" || true
      dfree "after ingest cleanup"
      echo "::error::pull failed after 8 attempts"; exit 1
    fi
  fi
  docker run -d --name ace-step --restart unless-stopped --gpus all --network comfynet \
    --health-cmd "python3 -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=5)\"" \
    --health-interval 30s --health-timeout 10s --health-retries 3 --health-start-period 20m \
    -e ACESTEP_MODE=api -e ACESTEP_LLM_BACKEND=pt \
    -e ACESTEP_CONFIG_PATH=acestep-v15-turbo -e ACESTEP_CONFIG_PATH2=acestep-v15-base \
    -e ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-1.7B -e ACESTEP_ON_DEMAND_MODEL_LOAD=true \
    -e ACESTEP_QUEUE_WORKERS=1 -e ACESTEP_API_WORKERS=1 \
    -e ACESTEP_API_HOST=0.0.0.0 -e ACESTEP_INIT_SERVICE=true -e UV_NO_SYNC=1 \
    -v $A/checkpoints:/app/checkpoints -v $A/output:/app/output -v $A/hf:/root/.cache/huggingface \
    "$IMG" >/dev/null
fi
# R4: single copy of the image
keep=$(docker image inspect -f '{{.Id}}' "$IMG")
for id in $(docker images -q --no-trunc "$REPO" | sort -u) $(docker images -q --no-trunc -f dangling=true | sort -u); do
  [ "$id" = "$keep" ] && continue
  docker ps -aq --filter ancestor="$id" | grep -q . && { echo "keep $id (used)"; continue; }
  echo "remove extra copy $id"; docker rmi "$id" || true
done
dfree "after dedupe"
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}'
for i in $(seq 1 100); do
  s=$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{end}}' ace-step)
  [ "${s#*/}" = healthy ] && { echo "ace-step healthy"; dfree end; exit 0; }
  [ "${s%/*}" = running ] || break
  sleep 12
done
docker logs --tail 40 ace-step 2>&1
echo "::error::ace-step not healthy ($s)"; exit 1
