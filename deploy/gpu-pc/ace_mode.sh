#!/bin/sh
# ace_mode.sh prod|xl — ace-step в нужной VRAM-конфигурации, ждёт healthy (до 18 мин).
# root-cause: t_f3937fb8 — образ ghcr ace-step-1.5:latest = upstream dce6214 (v0.1.8), в нём НЕТ
# ACESTEP_ON_DEMAND_MODEL_LOAD (появился в 7202bc3, 28.08): XL из body молча шёл на turbo, а fallback
# /v1/init грузил XL (9 ГБ bf16) поверх base+LM на RTX 5070 11.9 ГБ (upstream: XL на 8-12GB = нет) ->
# задача status=0 навсегда, xl_solo VARIANT-FAIL, «A/B не собран» (39106389601, 40022391620).
# xl = XL-sft единственным DiT-слотом (без base), offload_to_cpu авто (<20 ГБ); prod = turbo+base.
# Старый контейнер удаляется ДО старта нового: два набора весов одновременно не влезают в 12 ГБ.
set -eu
case "${1:-}" in
  prod) P=acestep-v15-turbo; S="-e ACESTEP_CONFIG_PATH2=acestep-v15-base" ;;
  xl)   P=acestep-v15-xl-sft; S="" ;;
  *) echo "usage: ace_mode.sh prod|xl"; exit 2 ;;
esac
A=/run/desktop/mnt/host/c/dockerlocal/ace15
IMG=$(docker inspect -f '{{.Config.Image}}' ace-step 2>/dev/null || echo ghcr.io/ace-step/ace-step-1.5:latest)
envs=$(docker inspect -f '{{json .Config.Env}}' ace-step 2>/dev/null || echo none)
# root-cause: t_860a1c4b — «уже нужный режим» только если есть UV_NO_SYNC=1, иначе пересоздать
if echo "$envs" | grep -q "\"ACESTEP_CONFIG_PATH=$P\"" && echo "$envs" | grep -q '"UV_NO_SYNC=1"' && { [ -n "$S" ] || ! echo "$envs" | grep -q ACESTEP_CONFIG_PATH2; }; then
  echo "ace_mode: уже $1"; docker start ace-step >/dev/null 2>&1 || :
else
  echo "ace_mode: пересоздаю ace-step -> $1 (primary=$P)"
  # root-cause: t_f3937fb8 — janitor guard_ace пересоздаёт ace-step, если увидит его отсутствие между rm и run
  # (гонка 25.10, test_janitor_sync): второй заход убирает его копию (prod-env) и ставит нужную.
  for try in 1 2; do
  docker rm -f ace-step >/dev/null 2>&1 || :
  docker run -d --name ace-step --restart unless-stopped --gpus all --network comfynet \
    --health-cmd "python3 -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=5)\"" \
    --health-interval 30s --health-timeout 10s --health-retries 3 --health-start-period 20m \
    -e ACESTEP_MODE=api -e ACESTEP_LLM_BACKEND=pt -e ACESTEP_CONFIG_PATH=$P $S \
    -e ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-1.7B -e ACESTEP_QUEUE_WORKERS=1 -e ACESTEP_API_WORKERS=1 \
    -e ACESTEP_API_HOST=0.0.0.0 -e ACESTEP_INIT_SERVICE=true -e UV_NO_SYNC=1 \
    -v $A/checkpoints:/app/checkpoints -v $A/output:/app/output -v $A/hf:/root/.cache/huggingface \
    "$IMG" >/dev/null && break
  [ $try = 2 ] && { echo "::error::ace_mode: docker run ace-step не удался"; exit 1; }
  done
fi
for i in $(seq 1 72); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' ace-step 2>/dev/null)" = healthy ] && { echo "ace_mode: $1 healthy"; exit 0; }
  sleep 15
done
docker logs --tail 60 ace-step 2>&1
echo "::error::ace_mode $1: ace-step не healthy за 18 мин"; exit 1
