#!/usr/bin/env bash
# t_5cdbb967: пересоздание контейнера раннера aicontent-factory без роста RW-слоя.
# Usage: runner-swap.sh <release|pc> <force|auto>
#   auto  = свап только если RW-слой > 1 ГБ. Оба режима ждут простоя целевого раннера (джобу не рвут).
# Что держит слой < 1 ГБ:
#   - образ acf-runner:<hash> = myoung34 + ffmpeg (apt-чинилки ci.yml/daily-* больше не пишут ~2 ГБ в слой);
#   - /tmp и /root/.cache — именованные тома (uv-cache/xlv/venv/pip вне слоя), ротация — janitor purge_tmp.
# Запускать с раннера ci (не цель свапа): stop/rm целевого контейнера убил бы свою же джобу.
# У pc-acf метки pc+release — runs-on release может попасть на него же.
set -euo pipefail
TARGET=${1:?release|pc}; MODE=${2:-force}
LIMIT=$((1000*1000*1000))
if [ "$TARGET" = release ]; then
  NAME=gh-runner-acf-release; RUNNER_NAME=pc-acf-release; LBL=release; WORK=/tmp/runner/acf-release
else
  NAME=gh-runner-aicontent-factory; RUNNER_NAME=pc-acf; LBL=pc; WORK=/tmp/runner/aicontent-factory
fi
VOL=$NAME-work

rw=$(docker inspect --size -f '{{.SizeRw}}' "$NAME" 2>/dev/null || echo 0)
echo "before: $NAME RW=$rw bytes"
if [ "$MODE" = auto ]; then [ "$rw" -gt "$LIMIT" ] || { echo "RW < 1 GB, skip"; exit 0; }; fi
# не рвать чужую джобу: ждём простоя целевого раннера, иначе пропуск до следующего запуска
busy() { docker top "$NAME" -eo args 2>/dev/null | grep -q Runner.Worker; }
# паузы между джобами 2-4 с (логи 27.10) — опрос каждые 2 с, до 35 мин
for i in $(seq 1 1050); do busy || break; sleep 2; done
if busy; then echo "job still running on $NAME, skip"; exit 0; fi

DOCKERFILE='FROM myoung34/github-runner:ubuntu-noble
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*'
TAG=acf-runner:$(printf %s "$DOCKERFILE" | sha256sum | cut -c1-12)
docker image inspect "$TAG" >/dev/null 2>&1 || printf %s "$DOCKERFILE" | docker build -q -t "$TAG" -
docker run --rm --entrypoint ffmpeg "$TAG" -version | head -1

docker volume create gh-runner-uv-cache >/dev/null; docker volume create gh-runner-xlv >/dev/null
TMP="unbreak-$$"
# Регистрация общая ($NAME-data, reusage): пока старый контейнер держит сессию, новый получает
# "A session for this runner already exists" и не выходит в Listening (run 40423983175). Старый — стоп
# до старта нового; при неудаче — старый поднимается обратно.
docker stop -t 60 "$NAME" >/dev/null
docker run -d --name "$TMP" --restart unless-stopped --cpus 4 --memory 4g \
  -e REPO_URL=https://github.com/mytab0r/aicontent-factory -e RUNNER_SCOPE=repo \
  -e RUNNER_NAME="$RUNNER_NAME" -e LABELS="$LBL" -e RUNNER_TOKEN="${REG:?REG secret}" \
  -e RUNNER_WORKDIR="$WORK" -e CONFIGURED_ACTIONS_RUNNER_FILES_DIR=/runner/data \
  -e DISABLE_AUTOMATIC_DEREGISTRATION=true \
  -e AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache \
  -e ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE=/opt/actions-archive-cache -v gh-actions-archive-cache:/opt/actions-archive-cache \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$NAME-data:/runner/data" \
  -v gh-runner-aicontent-factory-tools:/opt/hostedtoolcache \
  -v "$NAME-tmp:/tmp" -v "$NAME-cache:/root/.cache" \
  -v gh-runner-uv-cache:/tmp/acf-uv-cache -v gh-runner-xlv:/tmp/xlv \
  -v "$VOL:$WORK" \
  "$TAG"
ok=0; for i in $(seq 1 60); do docker logs "$TMP" 2>&1 | grep -q "Listening for Jobs" && { ok=1; break; }; sleep 5; done
[ "$ok" = 1 ] || { echo "::error::new runner not listening, rollback"; docker logs --tail 30 "$TMP"; docker rm -f "$TMP"; docker start "$NAME"; exit 1; }
docker rm -f "$NAME-old" 2>/dev/null || true
docker rename "$NAME" "$NAME-old"
docker rename "$TMP" "$NAME"
for n in comfynet gpu-net; do docker network connect $n "$NAME" || true; done
for z in $(docker ps -aq --filter "name=recreate-" --filter "name=unbreak-"); do docker rm -f "$z" || true; done
docker images acf-runner --format '{{.Repository}}:{{.Tag}}' | grep -vx "$TAG" | xargs -r docker rmi 2>/dev/null || true
echo "after: $NAME RW=$(docker inspect --size -f '{{.SizeRw}}' "$NAME") bytes image=$TAG"
docker rm -f "$NAME-old" || true
