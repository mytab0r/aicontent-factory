#!/bin/sh
# Runs ON VPS: stream GHCR blob -> HF upload (no disk use on VPS; one blob at a time).
# Usage: vps_to_hf.sh <blob_fn_name> <ghcr_digest> ; delete HF file after PC confirmed? PC pulls once; keep simple: overwrite per blob.
set -eu
FN=$1; DG=$2
TOK=$(curl -fsSL "https://ghcr.io/token?scope=repository:ace-step/ace-step-1.5:pull" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')
API="https://ghcr.io/v2/ace-step/ace-step-1.5"
# HF upload: PUT to /api/datasets/<repo>/upload/main/<fn> via Xet/LFS requires chunked; use simple PUT (works for LFS-backed via upload-link):
SIZE=$(curl -fsSI -H "Authorization: Bearer $TOK" "$API/blobs/$DG" | grep -i content-length | tr -d '\r' | awk '{print $2}')
# stream GHCR -> stdin of curl PUT to HF upload URL; commit after.
UP=$(curl -fsS -X POST "https://huggingface.co/api/datasets/ace-step-relay/preupload/main" -H "Authorization: Bearer $HF_TOKEN" -H "Content-Type: application/json" -d "{\"files\":[\"$FN\"]}")
URL=$(echo "$UP" | python3 -c 'import json,sys;print(json.load(sys.stdin)["uploadUrls"][0])')
curl -fsSL -H "Authorization: Bearer $TOK" "$API/blobs/$DG" | curl -fsS -X PUT --data-binary @- "$URL" -H "Content-Type: application/octet-stream" -H "Content-Length: $SIZE"
curl -fsS -X POST "https://huggingface.co/api/datasets/ace-step-relay/commit/main" -H "Authorization: Bearer $HF_TOKEN" -H "Content-Type: application/json" -d "{\"title\":\"relay $FN\",\"summary\":\"$FN\"}"
echo "uploaded $FN"
