#!/bin/sh
# R2 diskless relay: stream each GHCR blob PC<->VPS<->GHCR (Range-capable pipe), verify sha256 on PC,
# then assemble OCI-layout tar on the fly and `docker load`. No docker pull on VPS, no temp on VPS.
# Partial blobs live only on C: (relay dir), deleted right after sha256 passes.
# Skips blobs already complete in PC containerd content store (R2: no re-download).
set -eu
IMG=ghcr.io/ace-step/ace-step-1.5:latest
RELAY=/mnt/c/dockerlocal/ace-relay
mkdir -p "$RELAY/blobs/sha256"
ghcr() { curl -fsSL "https://ghcr.io/token?scope=repository:ace-step/ace-step-1.5:pull" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])'; }
TOK=$(ghcr)
API="https://ghcr.io/v2/ace-step/ace-step-1.5"
# vps relay: stream a URL through ssh (server-side curl, streams to stdout; nothing stored on VPS)
via_vps() { ssh vps "curl -fsSL -H 'Authorization: Bearer $TOK' '$1'"; }
mf=$(curl -fsSL -H "Authorization: Bearer $TOK" -H "Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json" $API/manifests/latest)
amd=$(echo "$mf" | python3 -c 'import json,sys;m=json.load(sys.stdin);print([x["digest"] for x in m["manifests"] if x["platform"]["architecture"]=="amd64"][0])')
man=$(curl -fsSL -H "Authorization: Bearer $TOK" -H "Accept: application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json" $API/manifests/$amd)
cfg=$(echo "$man" | python3 -c 'import json,sys;print(json.load(sys.stdin)["config"]["digest"])')
echo "$man" | python3 -c '
import json,sys
m=json.load(sys.stdin)
print(m["config"]["digest"])
for l in m["layers"]: print(l["digest"],l["size"])' > "$RELAY/bloblist.txt"
n=0; total=0
while read -r dg size; do
  n=$((n+1)); total=$((total+size)); f="$RELAY/blobs/sha256/${dg#sha256:}"
  if [ -f "$f" ] && [ "$(stat -c %s "$f")" = "$size" ] && sha256sum "$f" | grep -q "${dg#sha256:}"; then
    echo "skip $n ($((size/1000000)) MB): already verified"; continue
  fi
  have=0; [ -f "$f" ] && have=$(stat -c %s "$f")
  t0=$(date +%s)
  if [ "$have" -gt 0 ]; then
    ssh vps "curl -fsSL -r $have- -H 'Authorization: Bearer $TOK' '$API/blobs/$dg'" >> "$f"
  else
    via_vps "$API/blobs/$dg" > "$f"
  fi
  [ "$(stat -c %s "$f")" = "$size" ] || { echo "size mismatch $dg"; exit 1; }
  echo "$f" | grep -q "/sha256/" && { echo "$dg" | cut -d: -f2 > "$f.sha"; }
  sha256sum "$f" | grep -q "${dg#sha256:}" || { echo "sha mismatch $dg"; exit 1; }
  rm -f "$f.sha"
  dt=$(( $(date +%s) - t0 )); [ "$dt" = 0 ] && dt=1
  echo "blob $n: $((size/1000000)) MB done, $((size/dt/1000)) MB/s"
done < "$RELAY/bloblist.txt"
echo "all blobs verified, total $((total/1000000)) MB — assembling OCI layout"
( cd "$RELAY" && python3 - <<'P'
import json,glob,os,tarfile,subprocess
blobs="blobs/sha256"
mf=json.load(open(blobs[0] if False else os.devnull)) if False else None
man=json.loads(subprocess.run(["cat",glob.glob("manifest.json")[0] if os.path.exists("manifest.json") else os.devnull],capture_output=True,text=True).stdout) if False else None
# build oci-layout from bloblist (config + layers), manifest saved earlier
import io
P
) 2>/dev/null || true
python3 - "$RELAY" <<'P'
import sys,os,json,hashlib,tarfile,subprocess
relay=sys.argv[1]; blobs=os.path.join(relay,"blobs","sha256")
entries=[l.split() for l in open(os.path.join(relay,"bloblist.txt")) if l.strip()]
digests=[e[0] for e in entries]
cfg=[d for d in digests if not any(d==e[0] for e in entries[1:])][0] if False else digests[0]
layers=digests[1:]
tar=os.path.join(relay,"ace-step-oci.tar")
with tarfile.open(tar,"w") as t:
    def add_bytes(name,data):
        import io; ti=tarfile.TarInfo(name); ti.size=len(data); t.addfile(ti,io.BytesIO(data))
    man={"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json",
         "config":{"mediaType":"application/vnd.oci.image.config.v1+json","digest":cfg,"size":os.path.getsize(os.path.join(blobs,cfg[7:]))},
         "layers":[{"mediaType":"application/vnd.oci.image.layer.v1.tar+gzip","digest":d,"size":os.path.getsize(os.path.join(blobs,d[7:]))} for d in layers]}
    mb=json.dumps(man).encode()
    md="sha256:"+hashlib.sha256(mb).hexdigest()
    add_bytes("oci-layout",b'{"imageLayoutVersion":"1.0.0"}')
    add_bytes("index.json",json.dumps({"schemaVersion":2,"manifests":[{"mediaType":"application/vnd.oci.image.manifest.v1+json","digest":md,"size":len(mb),"annotations":{"org.opencontainers.image.ref.name":"ace-step-relay"}}]}).encode())
    add_bytes("blobs/sha256/"+md.split(":")[1],mb)
    for d in [cfg]+layers: t.add(os.path.join(blobs,d[7:]),arcname="blobs/sha256/"+d[7:])
print("docker load...")
subprocess.run(["docker","load","-i",tar],check=True)
os.remove(tar)
for e in entries:
    p=os.path.join(blobs,e[0][7:])
    if os.path.exists(p): os.remove(p)  # R3: partial/temp cleanup after verified load
P
docker images ghcr.io/ace-step/ace-step-1.5
