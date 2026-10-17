#!/bin/sh
# Гейт диска: не начинать скачивание весов/образов без места.
# Использование: disk_gate.sh <нужно_ГБ> [точка_монтирования]
set -e
need=${1:?usage: disk_gate.sh <GB_needed> [mount]}
mount=${2:-/opt/data}
free_kb=$(df -k "$mount" | awk 'NR==2 {print $4}')
need_kb=$((need * 1024 * 1024))
if [ "$free_kb" -lt "$need_kb" ]; then
  echo "disk_gate: на $mount свободно $((free_kb / 1024 / 1024)) ГБ, нужно ${need} ГБ — отмена" >&2
  exit 1
fi
echo "disk_gate: OK $((free_kb / 1024 / 1024)) ГБ свободно (нужно ${need} ГБ) на $mount"
