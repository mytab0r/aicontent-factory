import json, os, sys
from audiobox_aesthetics.infer import initialize_predictor
p = initialize_predictor()
fs = sorted(os.path.join(sys.argv[1], f) for f in os.listdir(sys.argv[1]))
for i in range(0, len(fs), 4):
    for f, s in zip(fs[i:i + 4], p.forward([{"path": f} for f in fs[i:i + 4]])):
        print(json.dumps({"path": f}) + "\t" + json.dumps(s), flush=True)
