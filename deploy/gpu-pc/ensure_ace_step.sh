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

# R1 within this runner; lock wait is bounded too (t_14d314c2)
exec 9>"${ACE_LOCK:-/tmp/ensure_ace_step.lock}"; flock -w "${ACE_LOCK_WAIT_S:-600}" 9 || { echo "::error::ensure_ace_step lock busy"; exit 1; }
dfree start
if docker inspect ace-step >/dev/null 2>&1; then
  [ "${1:-}" = restart ] && docker restart ace-step >/dev/null || docker start ace-step >/dev/null 2>&1 || true
else
  echo "ace-step missing -> recreate"
  if ! docker image inspect "$IMG" >/dev/null 2>&1; then
    # root-cause t_14d314c2: runs 39195973181/39201205845/39205125539 hit the step timeout (60/280/280 min):
    # PC->ghcr pull fails after ~70 min per attempt ("commit failed: rename", "short read ... unexpected EOF"),
    # a 10-attempt loop had no overall deadline, the slow-rate monitor never fired on fast-but-failing pulls,
    # and pkill left the retry loop running. Now: one pull inside a hard budget (timeout kills the whole
    # process group), then the HF relay. Every phase is bounded and fails with ::error:: instead of hanging.
    budget=${ACE_PULL_BUDGET_S:-1800}
    rc=0; timeout "$budget" docker pull "$IMG" >/tmp/pull.log 2>&1 || rc=$?
    if [ $rc = 0 ]; then
      echo "pull ok"
    else
      [ $rc = 124 ] && echo "pull exceeded ${budget}s budget -> HF relay" || echo "pull failed rc=$rc -> HF relay"
      echo "=== pull.log tail ==="; tail -5 /tmp/pull.log 2>/dev/null || :
      # R3: drop stale containerd ingest (partial blobs) left by the failed pull
      dfree "before ingest cleanup"
      host "find $INGEST -mindepth 1 -maxdepth 1 -type d -mmin +10 -exec rm -rf {} +" || echo "ingest cleanup skipped"
      # HF relay: download runs inside hermes-runner (D: mount), tar loaded by this runner
      # run the checked-out scripts, not a stale hand-copied version on D: (t_d80ff074)
      docker exec hermes-runner mkdir -p /work/dockerlocal/ace-relay
      docker cp deploy/gpu-pc/oci_pack.py hermes-runner:/work/dockerlocal/ace-relay/oci_pack.py
      docker cp deploy/gpu-pc/ace_relay.sh hermes-runner:/work/dockerlocal/ace-relay/ace_relay.sh
      docker cp deploy/gpu-pc/hf_get.sh hermes-runner:/work/dockerlocal/ace-relay/hf_get.sh
      docker cp deploy/gpu-pc/ace-step-manifest.json hermes-runner:/work/dockerlocal/ace-relay/ace-step-manifest.json
      docker exec hermes-runner sh /work/dockerlocal/ace-relay/ace_relay.sh || { echo "::error::hf relay download failed"; exit 1; }
      # stream tar (no cp copy: D: peak stays 1x image)
      timeout 3600 docker exec hermes-runner cat /work/dockerlocal/ace-relay/ace-step-oci.tar | timeout 3600 docker load || { echo "::error::docker load failed"; exit 1; }
      docker exec hermes-runner rm -f /work/dockerlocal/ace-relay/ace-step-oci.tar
      docker exec hermes-runner sh -c 'rm -f /work/dockerlocal/ace-relay/blobs/sha256/*'
      echo "relay complete, temps cleaned"
    fi
    docker image inspect "$IMG" >/dev/null || { echo "::error::image still missing"; exit 1; }
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
