#!/bin/sh
# Гейт перед любой загрузкой на ПК: отказ, если после неё на целевом диске останется меньше пола.
# usage: disk_gate.sh <c|d> <need_gb>
#   c = веса/кэши/выходы (bind C:\dockerlocal\<модель>), d = образы/сборки (docker_data.vhdx на D:).
# Пороги только из disk_floors.env. DISK_FREE_GB = подмена замера (тесты).
# Замер (t_096e2d0d): DISK_FREE_GB → docker (alpine df) → host-df (монтирование того же диска в WSL:
# /run/desktop/mnt/host/<drv>, для d ещё /work = D:) → отказ exit 2. Молча НЕ проходит без цифры.
set -eu
drv=${1:?usage: disk_gate.sh <c|d> <need_gb>}; need=${2:?need_gb}
. "$(dirname "$0")/disk_floors.env"
case $drv in c) floor=$DISK_FLOOR_C_GB;; d) floor=$DISK_FLOOR_D_GB;; *) echo "DISK GATE: неизвестный диск '$drv' (c|d)"; exit 2;; esac

free=""
m=""

# 1) подмена замера (тесты, workflows с известным объёмом)
if [ -n "${DISK_FREE_GB:-}" ]; then free=$DISK_FREE_GB; m="env"; fi

# 2) docker: df внутри контейнера по host-bind того же диска. В воркере на ПК docker API
#    за auth-proxy отдаёт 401 (не в allowlist) — тогда идём ниже, не падаем.
if [ -z "$free" ]; then
  kb=$(timeout 30 docker run --rm -v "/run/desktop/mnt/host/$drv:/x:ro" alpine:3.20 df -k /x 2>/dev/null | awk 'NR==2{print $4}' || true)
  case $kb in ''|*[!0-9]*) ;; *) free=$(( kb / 1048576 )); m="docker" ;; esac
fi

# 3) host-df: тот же диск, смонтированный в WSL. DISK_HOST_DF_PATHS — явный список путей
#    (тесты / нестандартное монтирование); пустое значение = кандидатов нет.
if [ -z "$free" ]; then
  if [ "${DISK_HOST_DF_PATHS+set}" = set ]; then
    paths=$DISK_HOST_DF_PATHS
  else
    paths="/run/desktop/mnt/host/$drv"
    [ "$drv" = d ] && paths="$paths /work"
  fi
  for path in $paths; do
    [ -d "$path" ] || continue
    kb=$(df -k "$path" 2>/dev/null | awk 'NR==2{print $4}' || true)
    case $kb in ''|*[!0-9]*) continue ;; esac
    free=$(( kb / 1048576 )); m="host-df:$path"
    break
  done
fi

# 4) fail-closed: ни одного реального замера — отказ, а не «0G free» и не тихий проход
if [ -z "$free" ]; then
  echo "DISK GATE: отказ — диск $drv не измерить: docker недоступен и host-df не найден (fail-closed)"
  exit 2
fi

after=$((free - need))
echo "disk $drv: free ${free}G, need ${need}G, after ${after}G, floor ${floor}G, measure=$m"
[ "$after" -ge "$floor" ] || { echo "DISK GATE: отказ — после загрузки ${after}G < пола ${floor}G на $drv:"; exit 1; }
