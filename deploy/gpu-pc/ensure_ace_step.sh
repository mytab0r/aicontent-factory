#!/bin/sh
# Idempotent: ace-step (ACE-Step 1.5 REST :8001, comfynet) exists, running, healthy.
# Self-heal for "No such container"/missing image (t_03efb867, 19.10): recreate + pull, never prune.
# Usage: sh deploy/gpu-pc/ensure_ace_step.sh [restart]
set -eu
IMG=ghcr.io/ace-step/ace-step-1.5:latest
A=/run/desktop/mnt/host/c/dockerlocal/ace15
if docker inspect ace-step >/dev/null 2>&1; then
  [ "${1:-}" = restart ] && docker restart ace-step >/dev/null || docker start ace-step >/dev/null 2>&1 || true
else
  echo "ace-step missing -> recreate"
  if ! docker image inspect "$IMG" >/dev/null 2>&1; then
    # VHDX on D: grows only if docker-internal free space runs out; gate on the inner fs.
    inner=$(docker run --rm --privileged --pid=host alpine:3.20 nsenter -t 1 -m -- df -Pk /var/lib/docker 2>/dev/null | awk 'NR==2{print int($4/1048576)}')
    echo "docker inner free: ${inner:-?} GB"
    [ "${inner:-0}" -ge 20 ] || { echo "::error::docker inner free < 20 GB, pull refused"; exit 1; }
    for i in 1 2 3; do docker pull -q "$IMG" && break; sleep 30; done
  fi
  docker run -d --name ace-step --restart unless-stopped --gpus all --network comfynet \
    --health-cmd "python3 -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=5)\"" \
    --health-interval 30s --health-timeout 10s --health-retries 3 --health-start-period 20m \
    -e ACESTEP_MODE=api -e ACESTEP_LLM_BACKEND=pt \
    -e ACESTEP_CONFIG_PATH=acestep-v15-turbo -e ACESTEP_CONFIG_PATH2=acestep-v15-base \
    -e ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-1.7B -e ACESTEP_ON_DEMAND_MODEL_LOAD=true \
    -e ACESTEP_QUEUE_WORKERS=1 -e ACESTEP_API_WORKERS=1 \
    -e ACESTEP_API_HOST=0.0.0.0 -e ACESTEP_INIT_SERVICE=true \
    -v $A/checkpoints:/app/checkpoints -v $A/output:/app/output -v $A/hf:/root/.cache/huggingface \
    "$IMG" >/dev/null
fi
for i in $(seq 1 100); do
  s=$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{end}}' ace-step)
  [ "${s#*/}" = healthy ] && { echo "ace-step healthy"; exit 0; }
  [ "${s%/*}" = running ] || break
  sleep 12
done
docker logs --tail 40 ace-step 2>&1
echo "::error::ace-step not healthy ($s)"; exit 1
