"""t_d80ff074 regression: ace_relay.sh bloblist must be "<digest> <size>" for every blob.
Config line once lacked size -> CI failed with "download sha256:<id> incomplete". Run: python deploy/gpu-pc/test_ace_relay.py"""
import json, os, re, subprocess
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ace_relay.sh")).read()
gen = re.search(r"echo \"\$man\" \| (python3 -c '.*?') > \"\$RELAY/bloblist.txt\"", src).group(1)
guard = re.search(r"^awk 'NF!=2.*bloblist.txt\"$", src, re.M).group(0).replace('"$RELAY/bloblist.txt"', "/dev/stdin")
d = lambda c: "sha256:" + c * 64
man = json.dumps({"config": {"digest": d("c"), "size": 20094}, "layers": [{"digest": d("a"), "size": 10}, {"digest": d("b"), "size": 7}]})
out = subprocess.run(gen, shell=True, input=man, capture_output=True, text=True, check=True).stdout
assert out.splitlines() == [d("c") + " 20094", d("a") + " 10", d("b") + " 7"], out
assert subprocess.run(guard, shell=True, input=out, text=True).returncode == 0
bad = d("c") + "\n" + d("a") + " 10\n"   # the exact t_d80ff074 shape: config without size
assert subprocess.run(guard, shell=True, input=bad, capture_output=True, text=True).returncode != 0
print("ok: bloblist has sizes, guard rejects sizeless line")
