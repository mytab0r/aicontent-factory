import sys,os,json,hashlib,tarfile,io
relay,img=sys.argv[1],sys.argv[2]
blobs=os.path.join(relay,"blobs","sha256")
lines=[l.split() for l in open(os.path.join(relay,"bloblist.txt")) if l.strip()]
cfg,entries=lines[0][0],lines
man=json.load(open(os.path.join(relay,"manifest.json")))
def sz(d): return os.path.getsize(os.path.join(blobs,d[7:]))
m={"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json",
   "config":{"mediaType":man["config"]["mediaType"],"digest":cfg,"size":sz(cfg)},
   "layers":[{"mediaType":l["mediaType"],"digest":l["digest"],"size":sz(l["digest"])} for l in man["layers"]]}
mb=json.dumps(m).encode(); md="sha256:"+hashlib.sha256(mb).hexdigest()
repo="ghcr.io/ace-step/ace-step-1.5"
idx={"schemaVersion":2,"mediaType":"application/vnd.oci.image.index.v1+json","manifests":[{"mediaType":"application/vnd.oci.image.manifest.v1+json","digest":md,"size":len(mb),"annotations":{"org.opencontainers.image.ref.name":img}}]}
tar=os.path.join(relay,"ace-step-oci.tar")
with tarfile.open(tar,"w") as t:
    for name,data in [("oci-layout",b'{"imageLayoutVersion":"1.0.0"}'),("index.json",json.dumps(idx).encode()),("blobs/sha256/"+md[7:],mb)]:
        ti=tarfile.TarInfo(name); ti.size=len(data); t.addfile(ti,io.BytesIO(data))
    for d in [cfg]+[l["digest"] for l in man["layers"]]:
        p=os.path.join(blobs,d[7:])
        t.add(p,arcname="blobs/sha256/"+d[7:])
        os.remove(p)  # operator 16:40: peak D: = 1x image (7.2GB), not 2x
print("packed",tar)
