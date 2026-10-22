#!/bin/sh
# Runs INSIDE hermes-runner (D:\ = /work). Downloads ace-step blobs from HF relay dataset
# to D:\dockerlocal\ace-relay, sha256-verifies each, assembles OCI layout + tar on D:.
# gh-runner then docker-cp's the tar and docker-loads it, and deletes temps.
set -eu
RELAY=/work/dockerlocal/ace-relay
REPO=mytab0r/ace-step-relay
TOK=$(cat /work/hermes-codex/.relay-token)
mkdir -p "$RELAY/blobs/sha256"
GH_TOK=$(curl -fsSL "https://ghcr.io/token?scope=repository:ace-step/ace-step-1.5:pull" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')
API="https://ghcr.io/v2/ace-step/ace-step-1.5"
mf=$(curl -fsSL -H "Authorization: Bearer $GH_TOK" -H "Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json" $API/manifests/latest)
amd=$(echo "$mf" | python3 -c 'import json,sys;m=json.load(sys.stdin);print([x["digest"] for x in m["manifests"] if x["platform"]["architecture"]=="amd64"][0])')
man=$(curl -fsSL -H "Authorization: Bearer $GH_TOK" -H "Accept: application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json" $API/manifests/$amd)
echo "$man" > "$RELAY/manifest.json"
echo "$man" | python3 -c 'import json,sys;m=json.load(sys.stdin);print(m["config"]["digest"],m["config"]["size"]);[print(l["digest"],l["size"]) for l in m["layers"]]' > "$RELAY/bloblist.txt"
# root-cause t_d80ff074: config line once lacked size -> size="" -> "[: Illegal number" -> "download ... incomplete".
# Every line must be "<sha256:hex> <bytes>"; fail before any download otherwise.
awk 'NF!=2 || $1!~/^sha256:[0-9a-f]{64}$/ || $2!~/^[0-9]+$/ {print "::error::bad bloblist line " NR ": " $0; bad=1} END{exit bad}' "$RELAY/bloblist.txt"
TOTAL=$(awk '{s+=$2}END{print s}' "$RELAY/bloblist.txt")
n=0
while read -r dg size; do
  n=$((n+1)); hex=${dg#sha256:}; f="$RELAY/blobs/sha256/$hex"
  if [ -f "$f" ] && [ "$(stat -c %s "$f")" = "$size" ] && sha256sum "$f" | grep -q "$hex"; then echo "skip $n (verified on D:)"; continue; fi
  start=$(date +%s); waited=0
  while ! curl -fsSI -H "Authorization: Bearer $TOK" "https://huggingface.co/datasets/$REPO/resolve/main/$hex.blob" >/dev/null 2>&1; do
    sleep 30; waited=$((waited+30))
    [ "$waited" -ge 10800 ] && { echo "::error::blob $hex.blob not on HF after 3h"; exit 1; }
    echo "waiting blob $n ($hex) ${waited}s"
  done
  ok=""
  for att in 1 2 3 4 5 6 7 8; do
    if curl -fSL --retry 5 --retry-delay 5 --retry-all-errors -C - -H "Authorization: Bearer $TOK" "https://huggingface.co/datasets/$REPO/resolve/main/$hex.blob" -o "$f.part"; then ok=1; break; fi
    echo "download attempt $att failed (SSL/eof), resuming from $(stat -c %s "$f.part" 2>/dev/null || echo 0) bytes"
    sleep 10
  done
  [ -n "$ok" ] || { echo "::error::download $hex failed after retries"; exit 1; }
  mv "$f.part" "$f"
  [ "$(stat -c %s "$f")" = "$size" ] || { echo "::error::size mismatch $hex"; exit 1; }
  sha256sum "$f" | grep -q "$hex" || { echo "::error::sha mismatch $hex"; exit 1; }
  now=$(date +%s); dt=$((now-start)); [ "$dt" -lt 1 ] && dt=1
  done_b=$(du -sb "$RELAY/blobs" | cut -f1)
  echo "blob $n ok: $((done_b/1000000))/$((TOTAL/1000000)) MB, speed $((size/dt/1000000))MB/s"
done < "$RELAY/bloblist.txt"
python3 /work/dockerlocal/ace-relay/oci_pack.py "$RELAY" "ghcr.io/ace-step/ace-step-1.5:latest"
echo "oci tar ready: $RELAY/ace-step-oci.tar ($(du -m $RELAY/ace-step-oci.tar | cut -f1)MB)"
