"""Merge aesthetics scores into bench.json; check whether CE tracks popularity on the refs."""
import json, os
import numpy as np
aes = {}
for line in open("out/aes.tsv"):
    a, b = line.rstrip("\n").split("\t")
    aes[os.path.basename(json.loads(a)["path"]).rsplit(".", 1)[0]] = json.loads(b)
rep = json.load(open("out/bench.json"))
for fmt, v in rep.items():
    for x in v["refs"]: x.update(aes.get(x["id"], {}))
    for x in v["ours"]: x.update(aes.get(x["tag"], {}))
    rs = [x for x in v["refs"] if "CE" in x]
    rank = lambda a: np.argsort(np.argsort(a))
    if len(rs) > 3:
        v["ce_vs_views_spearman"] = float(np.corrcoef(rank([x["CE"] for x in rs]), rank([x["views"] for x in rs]))[0, 1])
    for k in ("CE", "PQ", "CU", "PC"):
        vals = [x[k] for x in rs if k in x]
        if vals: v["band"][k] = [round(float(np.percentile(vals, 10)), 2), round(float(np.percentile(vals, 90)), 2), round(float(np.median(vals)), 2)]
    print(fmt, "spearman CE~views", v.get("ce_vs_views_spearman"))
    for x in v["ours"]: print(fmt, x["tag"], "fit", x["fit"], "CE", x.get("CE"), "PQ", x.get("PQ"))
    print(fmt, "refs CE/PQ band", v["band"].get("CE"), v["band"].get("PQ"))
json.dump(rep, open("out/bench.json", "w"), indent=1, ensure_ascii=False)
