#!/bin/sh
# Runs INSIDE hermes-runner (D:\ = /work). Downloads ace-step blobs from HF relay dataset
# to D:\dockerlocal\ace-relay, sha256-verifies each, assembles OCI layout + tar on D:.
# gh-runner then docker-cp's the tar and docker-loads it, and deletes temps.
set -eu
RELAY=/work/dockerlocal/ace-relay
REPO=mytab0r/ace-step-relay
TOK=$(cat /work/hermes-codex/.relay-token)
mkdir -p "$RELAY/blobs/sha256"
# root-cause t_a75ee36f: relay is the fallback for a broken PC->ghcr path, yet it fetched the manifest
# from ghcr on the PC (run 39273454007: "curl: (6) Could not resolve host: ghcr.io" -> "pull + relay failed").
# Manifest is pinned in the repo (= blobs uploaded to HF); relay touches only HF.
MAN_DIGEST=sha256:c289cb5c0cbc60d428baa9283a49966d2fe54ecf2028fa254f99f164f3953159
cp "$(dirname "$0")/ace-step-manifest.json" "$RELAY/manifest.json"
sha256sum "$RELAY/manifest.json" | grep -q "^${MAN_DIGEST#sha256:} " || { echo "::error::pinned manifest digest mismatch"; exit 1; }
man=$(cat "$RELAY/manifest.json")
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
  # root-cause t_5dccab9e: HF CDN closes any single connection after ~205 s (runs 39289005487/39290291128:
  # "SSL_read: unexpected eof" at 1996 MiB -> "download <id> failed"). Ranged download, no retry loop.
  sh "$(dirname "$0")/hf_get.sh" "https://huggingface.co/datasets/$REPO/resolve/main/$hex.blob" "$f" -H "Authorization: Bearer $TOK" \
    || { echo "::error::download $hex failed (see hf_get range error above)"; exit 1; }
  [ "$(stat -c %s "$f")" = "$size" ] || { echo "::error::size mismatch $hex"; exit 1; }
  sha256sum "$f" | grep -q "$hex" || { echo "::error::sha mismatch $hex"; exit 1; }
  now=$(date +%s); dt=$((now-start)); [ "$dt" -lt 1 ] && dt=1
  done_b=$(du -sb "$RELAY/blobs" | cut -f1)
  echo "blob $n ok: $((done_b/1000000))/$((TOTAL/1000000)) MB, speed $((size/dt/1000000))MB/s"
done < "$RELAY/bloblist.txt"
python3 /work/dockerlocal/ace-relay/oci_pack.py "$RELAY" "ghcr.io/ace-step/ace-step-1.5:latest"
echo "oci tar ready: $RELAY/ace-step-oci.tar ($(du -m $RELAY/ace-step-oci.tar | cut -f1)MB)"
