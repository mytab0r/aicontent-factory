#!/bin/sh
# gpu_yield.sh stop|restore — 23.10: flint (llama-server -ngl 99) занял VRAM 12 ГБ RTX 5070,
# ace-step декодировал VAE на CPU, задачи банка висели до таймаута, банк 3 раза подряд пустой.
# Класс: любой чужой контейнер с GPU мешает генерации. Перед GPU-работой останавливаем всех
# running-контейнеров с DeviceRequests gpu, кроме ace-step; restore поднимает их обратно.
set -u
F=/tmp/acf-gpu-yielded.txt
case "${1:-}" in
stop)
  : > "$F.new"
  for n in $(docker ps --format '{{.Names}}'); do
    [ "$n" = ace-step ] && continue
    docker inspect -f '{{json .HostConfig.DeviceRequests}}' "$n" 2>/dev/null | grep -q gpu || continue
    echo "gpu_yield: стоп $n (держит GPU)"; docker stop -t 20 "$n" >/dev/null 2>&1 && echo "$n" >> "$F.new"
  done
  cat "$F.new" >> "$F" 2>/dev/null; rm -f "$F.new" ;;
restore)
  [ -s "$F" ] || exit 0
  for n in $(sort -u "$F"); do echo "gpu_yield: старт $n"; docker start "$n" >/dev/null 2>&1 || true; done
  rm -f "$F" ;;
*) echo "usage: gpu_yield.sh stop|restore"; exit 2 ;;
esac
