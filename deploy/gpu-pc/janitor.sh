#!/bin/sh
# PC docker janitor (runs in container docker-janitor, /j bind = C:\\Users\\magic\\hermes-ops\\janitor).
# Source of truth: repo deploy/gpu-pc/janitor.sh; host copy synced by .github/workflows/janitor-sync.yml.
# Edit in repo, merge, dispatch janitor-sync — never edit the host copy directly.
# conservative: only forbidden names; no prune of images/containers
BAD_CT='^(hya-|comfy|wan|findrec|gpu-check|netprobe|np-|probe-)'
BAD_VOL='^(comfy-|wan-|hya-|avatar-data)'
# Runner containers are long-lived: one-off jobs leave venvs/audio/caches in /tmp and ~/.cache inside the
# container layer (10.5 GB seen 15.10) -> docker vhdx on D: grows. Purge only regenerable stuff older than 12h
# (> any job timeout in use), never the bind-mounted workdir /tmp/runner, never volumes.
# ponytail: freed space is reused inside the vhdx; D: itself shrinks only after an offline vhdx compact.
purge_tmp() {
  for c in $(docker ps --format '{{.Names}}' | grep -E '^(gh-runner-|hermes-runner$|ace-step$)'); do
    docker exec "$c" sh -c 'find /tmp -mindepth 1 -maxdepth 1 ! -name runner ! -name .X11-unix -mmin +720 -exec rm -rf {} + 2>/dev/null
      for x in pip uv ms-playwright-tmp; do find /root/.cache/$x -mindepth 1 -maxdepth 1 -mmin +720 -exec rm -rf {} + 2>/dev/null; done; true' >/dev/null 2>&1
  done
}
# H-051: ace-step is protected - recreate if deleted, start if stopped >10 min. Never stop/rm it here.
# 25.10: recreate обязан ставить UV_NO_SYNC=1 (как в daily-video #239): без него entrypoint `uv run`
# пересинхронизирует venv (torch ~10 МБ/мин) и health висит в starting, выпуск падает.
# ponytail: единый источник recreate-описания с daily-video/ensure_ace_step; при смене образа/флагов править все три.
ACE_IMG=ghcr.io/ace-step/ace-step-1.5:latest
ACE_DIR=/run/desktop/mnt/host/c/dockerlocal/ace15
guard_ace() {
  st=$(docker inspect -f '{{.State.Status}}' ace-step 2>/dev/null) || {
    docker run -d --name ace-step --restart unless-stopped --gpus all --network comfynet \
      -e ACESTEP_MODE=api -e ACESTEP_LLM_BACKEND=pt -e ACESTEP_CONFIG_PATH=acestep-v15-turbo -e ACESTEP_CONFIG_PATH2=acestep-v15-base \
      -e ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-1.7B -e ACESTEP_ON_DEMAND_MODEL_LOAD=true -e ACESTEP_QUEUE_WORKERS=1 \
      -e ACESTEP_API_WORKERS=1 -e ACESTEP_API_HOST=0.0.0.0 -e ACESTEP_INIT_SERVICE=true -e UV_NO_SYNC=1 $ACE_IMG >/dev/null 2>&1 \
      && echo "ACE-STEP RECREATED $(date -u +%FT%TZ)" || echo "ACE-STEP RECREATE FAILED $(date -u +%FT%TZ)"
    return; }
  [ "$st" = running ] && return
  [ "$(docker inspect -f '{{.State.Status}}' hermes-runner 2>/dev/null)" = running ] || return  # game mode: leave stopped
  fin=$(docker inspect -f '{{.State.FinishedAt}}' ace-step); fin=$(date -u -D '%Y-%m-%dT%H:%M:%S' -d "${fin%.*}" +%s 2>/dev/null) || return
  [ $(( $(date -u +%s) - fin )) -gt 600 ] && docker start ace-step >/dev/null 2>&1 && echo "ACE-STEP STARTED $(date -u +%FT%TZ)"
}
while true; do
  guard_ace
  for c in $(docker ps -a --format '{{.Names}}'); do [ "$c" = ace-step ] && continue; echo "$c" | grep -Eq "$BAD_CT" && docker rm -f "$c" >/dev/null 2>&1; done
  for v in $(docker volume ls -q); do echo "$v" | grep -Eq "$BAD_VOL" && docker volume rm "$v" >/dev/null 2>&1; done
  # H-volprune 20.10: volume prune removed hermes-runner /opt/data (anon volume) during recreate -> kanban lost. NEVER prune volumes here.
  docker builder prune -f --filter until=24h >/dev/null 2>&1
  purge_tmp
  sleep 600
done
