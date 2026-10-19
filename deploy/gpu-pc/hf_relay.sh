#!/bin/sh
# R2 relay via Hugging Face (HF->PC 9-10MB/s, Range OK). VPS streams GHCR->HF upload (30MB/s),
# PC downloads with resume, sha256-checked; OCI layout assembled on C:, docker load, temp deleted.
# HF_TOKEN comes from repo secret (Actions env). One blob in flight; 4.67GB fits free space, second blob only after first uploaded+deleted.
set -eu
: "${HF_TOKEN:?HF_TOKEN required}"
IMG=ghcr.io/ace-step/ace-step-1.5:latest
RELAY=/mnt/c/dockerlocal/ace-relay
REPO=ace-step-relay
mkdir -p "$RELAY/blobs/sha256"
TOK=$(curl -fsSL "https://ghcr.io/token?scope=repository:ace-step/ace-step-1.5:pull" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')
API="https://ghcr.io/v2/ace-step/ace-step-1.5"
H="Authorization: Bearer $TOK"
mf=$(curl -fsSL -H "$H" -H "Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json" $API/manifests/latest)
amd=$(echo "$mf" | python3 -c 'import json,sys;m=json.load(sys.stdin);print([x["digest"] for x in m["manifests"] if x["platform"]["architecture"]=="amd64"][0])')
man=$(curl -fsSL -H "$H" -H "Accept: application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json" $API/manifests/$amd)
echo "$man" > "$RELAY/manifest.json"
echo "$man" | python3 -c 'import json,sys;m=json.load(sys.stdin);print(m["config"]["digest"]);[print(l["digest"],l["size"]) for l in m["layers"]]' > "$RELAY/bloblist.txt"
TOTAL=$(awk '{s+=$2}END{print s}' "$RELAY/bloblist.txt")
n=0
while read -r dg size; do
  n=$((n+1)); f="$RELAY/blobs/sha256/${dg#sha256:}"
  if [ -f "$f" ] && [ "$(stat -c %s "$f")" = "$size" ] && sha256sum "$f" | grep -q "${dg#sha256:}"; then echo "skip $n verified"; continue; fi
  fn=$(echo "$dg" | tr ':_' '__' | tr '/' '_')
  # PC resume download from HF if partial exists
  have=0; [ -f "$f" ] && have=$(stat -c %s "$f")
  if [ "$have" -lt "$size" ]; then
    if [ "$have" -gt 0 ]; then
      curl -fsSL -C - -H "Authorization: Bearer $HF_TOKEN" "https://huggingface.co/datasets/$REPO/resolve/main/$fn" >> "$f" || true
    else
      curl -fSL -H "Authorization: Bearer $HF_TOKEN" "https://huggingface.co/datasets/$REPO/resolve/main/$fn" -o "$f" || true
    fi
  fi
  [ "$(stat -c %s "$f" 2>/dev/null || echo 0)" = "$size" ] || { echo "::error::download $dg incomplete"; exit 1; }
  sha256sum "$f" | grep -q "${dg#sha256:}" || { echo "::error::sha mismatch $dg"; exit 1; }
  echo "blob $n done $((size/1000000))MB, total so far $(du -sm "$RELAY/blobs" | cut -f1)MB/$((TOTAL/1000000))MB"
done < "$RELAY/bloblist.txt"
python3 deploy/gpu-pc/oci_pack.py "$RELAY" "$IMG"
docker load -i "$RELAY/ace-step-oci.tar"
rm -f "$RELAY/ace-step-oci.tar" "$RELAY"/blobs/sha256/*
echo "relay complete, temp cleaned"
