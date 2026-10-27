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
# t_5cdbb967: RW-слой gh-runner-acf-release / gh-runner-aicontent-factory рос до 6-14 ГБ: apt-чинилки ffmpeg
# (~2 ГБ /usr), /tmp (uv-cache, xlv, workdir /tmp/runner/work из старой регистрации), /root/.cache.
# Механизм: раннер с RW > 1 ГБ и без джобы пересоздаётся на образе acf-runner (myoung34 + ffmpeg), /tmp и
# /root/.cache — именованные тома (вне слоя; ротация — purge_tmp выше). Конфиг (REPO/имя/метки/токен)
# берётся из docker inspect старого контейнера, регистрация переиспользуется из тома $n-data.
# ponytail: окно гонки — джоба, выданная между проверкой простоя и stop (паузы 2-4 с), будет прервана.
RUNNER_DF='FROM myoung34/github-runner:ubuntu-noble
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*'
# ps без колонки pid -> docker top падает ("Couldn't find PID field") -> раньше «простой» = свап
# посреди bank fill (27.10 03:41). Ошибка top = занят (fail-closed).
runner_busy() { out=$(docker top "$1" -eo pid,args 2>/dev/null) || return 0; echo "$out" | grep -q Runner.Worker; }
swap_runner() {
  n=$1
  # прерванный прошлый свап: вернуть старый контейнер
  docker inspect "$n" >/dev/null 2>&1 || { docker rename "$n-old" "$n" && docker start "$n"; return; } >/dev/null 2>&1
  rw=$(docker inspect --size -f '{{.SizeRw}}' "$n" 2>/dev/null) || return
  [ "${rw:-0}" -gt 1000000000 ] || return
  runner_busy "$n" && return; sleep 5; runner_busy "$n" && return
  tag=acf-runner:$(printf %s "$RUNNER_DF" | sha256sum | cut -c1-12)
  docker image inspect "$tag" >/dev/null 2>&1 || printf %s "$RUNNER_DF" | docker build -q -t "$tag" - >/dev/null || return
  envf=/tmp/swap-$n.env
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$n" \
    | grep -E '^(REPO_URL|RUNNER_SCOPE|RUNNER_NAME|LABELS|RUNNER_TOKEN|RUNNER_WORKDIR|DISABLE_AUTOMATIC_DEREGISTRATION)=' > "$envf"
  work=$(sed -n 's/^RUNNER_WORKDIR=//p' "$envf")
  docker volume create gh-runner-uv-cache >/dev/null; docker volume create gh-runner-xlv >/dev/null
  docker rm -f "$n-old" >/dev/null 2>&1
  docker stop -t 60 "$n" >/dev/null && docker rename "$n" "$n-old" || { rm -f "$envf"; docker start "$n" >/dev/null 2>&1; return; }
  docker run -d --name "$n" --restart unless-stopped --dns 192.168.65.7 --dns 8.8.8.8 --dns 77.88.8.8 --cpus 4 --memory 4g \
    --env-file "$envf" -e CONFIGURED_ACTIONS_RUNNER_FILES_DIR=/runner/data -e AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache \
    -e ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE=/opt/actions-archive-cache -v gh-actions-archive-cache:/opt/actions-archive-cache \
    -v /var/run/docker.sock:/var/run/docker.sock -v "$n-data:/runner/data" \
    -v gh-runner-aicontent-factory-tools:/opt/hostedtoolcache \
    -v "$n-tmp:/tmp" -v "$n-cache:/root/.cache" \
    -v gh-runner-uv-cache:/tmp/acf-uv-cache -v gh-runner-xlv:/tmp/xlv -v "$n-work:$work" \
    "$tag" >/dev/null
  rm -f "$envf"
  ok=0; for i in $(seq 1 60); do docker logs "$n" 2>&1 | grep -q "Listening for Jobs" && { ok=1; break; }; sleep 5; done
  if [ $ok = 1 ]; then
    for net in comfynet gpu-net; do docker network connect $net "$n" >/dev/null 2>&1; done
    docker rm -f "$n-old" >/dev/null 2>&1
    echo "RUNNER SWAPPED $n rw=$rw -> $(docker inspect --size -f '{{.SizeRw}}' "$n") $(date -u +%FT%TZ)"
  else
    echo "RUNNER SWAP FAILED $n, rollback $(date -u +%FT%TZ)"; docker logs --tail 5 "$n" 2>&1
    docker rm -f "$n" >/dev/null 2>&1; docker rename "$n-old" "$n"; docker start "$n" >/dev/null
  fi
}
while true; do
  guard_ace
  for c in $(docker ps -a --format '{{.Names}}'); do [ "$c" = ace-step ] && continue; echo "$c" | grep -Eq "$BAD_CT" && docker rm -f "$c" >/dev/null 2>&1; done
  for v in $(docker volume ls -q); do echo "$v" | grep -Eq "$BAD_VOL" && docker volume rm "$v" >/dev/null 2>&1; done
  # H-volprune 20.10: volume prune removed hermes-runner /opt/data (anon volume) during recreate -> kanban lost. NEVER prune volumes here.
  docker builder prune -f --filter until=24h >/dev/null 2>&1
  purge_tmp
  for r in gh-runner-acf-release gh-runner-aicontent-factory; do swap_runner $r; done
  sleep 600
done
