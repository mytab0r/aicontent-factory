#!/bin/sh
# t_265d0147: файлы прогона -> C:\dockerlocal\acf-out\<run_id>\ вместо GitHub artifacts
# (квота storage Free считается в ГБ-часах за месяц на весь аккаунт; удаление/retention её не возвращают).
# usage: acf_out.sh put <run_id> <file>...   — копия (пути сохраняются); несуществующие файлы пропускаются
#        acf_out.sh get <run_id> <dest_dir>  — чтение того, что положил другой job/прогон
#        acf_out.sh keep <run_id>            — пометка keep (ретеншн не трогает)
# Ретеншн (перед каждым put): каталоги старше 7 дней удаляются, кроме содержащих файл `keep`;
# сумма > 20 ГБ (с учётом нового) — удаляются старейшие не-keep. Пол свободного места C: — disk_gate.sh
# (порог только из disk_floors.env, t_40bfcd35). Раннер = контейнер: пишем через docker run + tar по stdin.
# ACF_OUT_ROOT = локальный каталог вместо docker (тесты; только там ACF_OUT_CAP_KB подменяет лимит); DISK_FREE_GB — подмена замера в disk_gate.sh.
set -eu
op=${1:?usage: acf_out.sh put|get|keep <run_id> ...}; run=${2:?run_id}; shift 2
case $run in *[!0-9A-Za-z_-]*|'') echo "acf_out: плохой run_id '$run'"; exit 2;; esac
INNER='set -eu
case $MODE in
prune)
  now=$(date +%s)
  for d in "$O"/*/; do [ -d "$d" ] || continue
    [ -e "$d/keep" ] && continue
    [ $((now - $(stat -c %Y "$d"))) -gt 604800 ] && rm -rf "$d"
  done
  cap=${CAPK:-$((20 * 1048576))}; tot=$(du -sk "$O" | cut -f1)
  for d in $(ls -1tr "$O"); do
    [ $((tot + NEEDK)) -le $cap ] && break
    [ -e "$O/$d/keep" ] && continue
    s=$(du -sk "$O/$d" | cut -f1); rm -rf "${O:?}/$d"; tot=$((tot - s))
  done
  [ $((tot + NEEDK)) -le $cap ] || { echo "acf_out: лимит 20 ГБ (keep-каталоги не удаляются)" >&2; exit 1; };;
write) mkdir -p "$O/$RUN"; tar -x -C "$O/$RUN"; touch "$O/$RUN"; du -sh "$O/$RUN"; ls -la "$O/$RUN";;
keep) mkdir -p "$O/$RUN"; touch "$O/$RUN/keep";;
read) test -d "$O/$RUN" || { echo "acf_out: нет $RUN" >&2; exit 1; }; tar -c -C "$O/$RUN" .;;
esac'
H=/run/desktop/mnt/host/c/dockerlocal/acf-out
inner() {  # MODE NEEDK; stdin/stdout проходят насквозь
  if [ -n "${ACF_OUT_ROOT:-}" ]; then mkdir -p "$ACF_OUT_ROOT"; MODE=$1 NEEDK=$2 RUN=$run O=$ACF_OUT_ROOT CAPK=${ACF_OUT_CAP_KB:-} sh -c "$INNER"
  else docker run --rm -i -e MODE="$1" -e NEEDK="$2" -e RUN="$run" -e O=/o -v "$H:/o" alpine:3.20 sh -c "$INNER"; fi
}
case $op in
put)
  files=""; for f in "$@"; do [ -f "$f" ] && files="$files $f"; done
  [ -n "$files" ] || { echo "acf_out: нечего класть"; exit 0; }
  # shellcheck disable=SC2086
  needk=$(du -ck $files | tail -1 | cut -f1)
  inner prune "$needk" </dev/null
  sh "$(dirname "$0")/disk_gate.sh" c $(( (needk + 1048575) / 1048576 ))
  # shellcheck disable=SC2086
  tar -c -f - $files | inner write 0
  printf 'acf_out: C:\\dockerlocal\\acf-out\\%s\\ <-%s\n' "$run" "$files";;
keep) inner keep 0 </dev/null;;
get) dest=${1:?dest_dir}; mkdir -p "$dest"; inner read 0 </dev/null | tar -x -C "$dest";;
*) echo "acf_out: неизвестная операция '$op'"; exit 2;;
esac
