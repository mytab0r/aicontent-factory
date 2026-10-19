#!/bin/sh
# Гейт перед любой загрузкой на ПК: отказ, если после неё на целевом диске останется меньше пола.
# usage: disk_gate.sh <c|d> <need_gb>
#   c = веса/кэши/выходы (bind C:\dockerlocal\<модель>), d = образы/сборки (docker_data.vhdx на D:).
# Пороги только из disk_floors.env. DISK_FREE_GB = подмена замера (тесты).
set -eu
drv=${1:?usage: disk_gate.sh <c|d> <need_gb>}; need=${2:?need_gb}
. "$(dirname "$0")/disk_floors.env"
case $drv in c) floor=$DISK_FLOOR_C_GB;; d) floor=$DISK_FLOOR_D_GB;; *) echo "DISK GATE: неизвестный диск '$drv' (c|d)"; exit 2;; esac
if [ -n "${DISK_FREE_GB:-}" ] && [ "$DISK_FREE_GB" -gt 0 ] 2>/dev/null; then free=$DISK_FREE_GB; else
  free=$(( $(docker run --rm -v /run/desktop/mnt/host/$drv:/x:ro alpine:3.20 df -k /x | awk 'NR==2{print $4}') / 1048576 ))
fi
after=$((free - need))
echo "disk $drv: free ${free}G, need ${need}G, after ${after}G, floor ${floor}G"
[ "$after" -ge "$floor" ] || { echo "DISK GATE: отказ — после загрузки ${after}G < пола ${floor}G на $drv:"; exit 1; }
