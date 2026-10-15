#!/bin/sh
# Disk gate before any download/pull on the owner's PC. Refuses if the drive would drop below the floor.
# usage: disk_gate.sh <c|d> <need_gb> [floor_gb]   (D: holds docker_data.vhdx; owner rule: D: > 40 GB free)
set -e
drv=$1; need=$2; floor=${3:-40}
kb=$(docker run --rm -v /run/desktop/mnt/host/$drv:/x:ro alpine:3.20 df -k /x | awk 'NR==2{print $4}')
free=$((kb/1048576)); after=$((free-need))
echo "disk $drv: free ${free}G, need ${need}G, after ${after}G, floor ${floor}G"
[ "$after" -ge "$floor" ] || { echo "DISK GATE: refusing download, would leave ${after}G < ${floor}G on $drv:"; exit 1; }
