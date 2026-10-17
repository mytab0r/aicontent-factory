#!/usr/bin/env python3
"""Спайк t_737ca0ec: та же пачка промптов через ACE-Step 1.5 (turbo = слот контейнера).
REST /release_task -> /query_result, без внешних зависимостей. Выход: out/ace_XX.mp3 + gen_log."""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE = os.environ["ACE15_ENDPOINT"].rstrip("/")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "spike-out")
PROMPTS = Path("deploy/gpu-pc/minimax/prompts")
ACE15_MAX_SEC = 600
(OUT / "ace").mkdir(parents=True, exist_ok=True)


def post(path, body, timeout=600):
    r = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=timeout))


def get(path):
    return urllib.request.urlopen(BASE + path, timeout=300).read()


log = (OUT / "ace_gen_log.jsonl").open("a")
for sp in sorted(PROMPTS.glob("*.json")):
    p = json.loads(sp.read_text())
    mp3 = OUT / "ace" / f"ace_{p['id']}.mp3"
    if mp3.exists():
        print(f"{p['id']}: уже есть", flush=True)
        continue
    body = {"prompt": p["caption"], "lyrics": "[Instrumental]" if p["type"].startswith("inst") else p["lyrics"],
            "audio_duration": min(120, ACE15_MAX_SEC), "bpm": p["bpm"], "key_scale": p["key"],
            "time_signature": "4", "batch_size": 1, "thinking": True,
            "use_random_seed": False, "seed": 41 + int(p["id"]), "audio_format": "mp3"}
    t0 = time.time()
    tid = post("/release_task", body)["data"]["task_id"]
    deadline = time.time() + 900
    while True:
        d = post("/query_result", {"task_id_list": [tid]})["data"][0]
        if d["status"] != 0:
            break
        if time.time() > deadline:
            raise SystemExit(f"ACE task {p['id']} timeout")
        time.sleep(3)
    gen_s = round(time.time() - t0, 1)
    ok = d["status"] == 1
    if ok:
        item = json.loads(d["result"])[0]
        mp3.write_bytes(get(item["file"]))
        dit = item.get("dit_model", "?")
    else:
        dit = f"FAILED: {str(d.get('result'))[:200]}"
    log.write(json.dumps({"id": p["id"], "type": p["type"], "bpm": p["bpm"], "gen_s": gen_s,
                          "ok": ok, "dit_model": dit}) + "\n")
    log.flush()
    print(p["id"], gen_s, dit, flush=True)
print("done", flush=True)
