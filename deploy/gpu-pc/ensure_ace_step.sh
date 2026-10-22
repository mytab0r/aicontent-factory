#!/bin/sh
# Idempotent: ace-step (ACE-Step 1.5 REST :8001, comfynet) exists, running, healthy.
# Self-heal for "No such container"/missing image (t_03efb867, 19.10).
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
ok=1   # pull path sets 0 on total failure; relay path stays success
dfree start
if docker inspect ace-step >/dev/null 2>&1; then
  [ "${1:-}" = restart ] && docker restart ace-step >/dev/null || docker start ace-step >/dev/null 2>&1 || true
else
  echo "ace-step missing -> recreate"
  if ! docker image inspect "$IMG" >/dev/null 2>&1; then
    # R1/R2: pull in background + progress monitor; abort to VPS mirror route if <3MB/s for 10min
    ( for i in 1 2 3 4 5 6 7 8 9 10; do
        docker pull "$IMG" >/tmp/pull.log 2>&1 && break
        echo "pull attempt $i failed" >>/tmp/pull.log; sleep 20
      done; touch /tmp/pull.done ) &
    total=7160000000  # amd64 compressed layers, owner measure 19.10
    slow=0; prev=0; pt=$(date +%s)
    while [ ! -f /tmp/pull.done ]; do
      sleep 60
      now=$(docker run --rm --privileged --pid=host alpine:3.20 sh -c 's=0; for d in /var/lib/desktop-containerd/daemon/io.containerd.content.v1.content/ingest/*/; do [ -f "$d/data" ] && s=$((s+$(stat -c %s "$d/data" 2>/dev/null||echo 0))); done; echo $s' || echo 0)
      dt=$(( $(date +%s) - pt )); rate=$(( dt>0 ? (now-prev)/dt/1000 : 0 ))
      echo "progress: $((now/1000000))/$((total/1000000)) MB ($((now*100/total))%) ${rate}KB/s | $(tail -1 /tmp/pull.log 2>/dev/null | cut -c1-80)"
      if [ "$rate" -lt 3000 ]; then slow=$((slow+1)); [ $slow -ge 10 ] && { echo "SLOW 10min: switching to VPS relay"; break; }; else slow=0; fi
      prev=$now; pt=$(date +%s)
    done
    if [ -f /tmp/pull.done ] && grep -q "Status: Downloaded" /tmp/pull.log; then
      rm -f /tmp/pull.done
    else
      echo "=== pull.log tail ==="; tail -5 /tmp/pull.log 2>/dev/null; pkill -f "docker pull" || true; sleep 3; rm -f /tmp/pull.done
      # HF relay: download runs inside hermes-runner (D: mount), tar loaded by this runner
      # run the checked-out scripts, not a stale hand-copied version on D: (t_d80ff074)
      docker exec hermes-runner mkdir -p /work/dockerlocal/ace-relay
      docker cp deploy/gpu-pc/oci_pack.py hermes-runner:/work/dockerlocal/ace-relay/oci_pack.py
      docker cp deploy/gpu-pc/ace_relay.sh hermes-runner:/work/dockerlocal/ace-relay/ace_relay.sh
      docker exec hermes-runner sh /work/dockerlocal/ace-relay/ace_relay.sh || { echo "::error::hf relay download failed"; exit 1; }
      # stream tar (no cp copy: D: peak stays 1x image)
      docker exec hermes-runner cat /work/dockerlocal/ace-relay/ace-step-oci.tar | docker load || { echo "::error::docker load failed"; exit 1; }
      docker exec hermes-runner rm -f /work/dockerlocal/ace-relay/ace-step-oci.tar
      docker exec hermes-runner sh -c 'rm -f /work/dockerlocal/ace-relay/blobs/sha256/*'
      echo "relay complete, temps cleaned"
    fi
    docker image inspect "$IMG" >/dev/null || { echo "::error::image still missing"; exit 1; }
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
    -e ACESTEP_API_HOST=0.0.0.0 -e ACESTEP_INIT_SERVICE=true \
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
