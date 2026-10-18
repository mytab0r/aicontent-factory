#!/usr/bin/env python3
"""Спайк t_737ca0ec: генерация MiniMax Music 3 (форк audio.cpp, CUDA).
Запускается ВНУТРИ контейнера minimax-spike. Веса /models (ro), промпты /work/prompts, выход /out.
1 попытка на трек (timeout 480 с), FALL — в лог, не в исключение."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BIN = "/src/build/bin/audiocpp_cli"
MODEL = os.environ.get("MM3_MODEL_DIR", "/models")
OUT = Path("/out")
PROMPTS = Path(os.environ.get("MM3_PROMPTS", "/work/prompts"))
TIMEOUT = int(os.environ.get("MM3_TIMEOUT", "480"))

OUT.mkdir(parents=True, exist_ok=True)

# Preflight: базовая загрузка assets.cpp требует эти дефолтные имена (symlink'и делает weights-шаг).
REQ = ["language_model_q4_0.gguf", "rvq_depth_decoder_bf16.gguf", "transformer_q4_0.gguf",
       "condition_encoder.gguf", "vocoder.gguf", "config/language_model.json",
       "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json"]
missing = [f for f in REQ if not (Path(MODEL) / f).exists()]
if missing:
    print("FAIL preflight, нет файлов:", ", ".join(missing), flush=True)
    sys.exit(2)

log = (OUT / "gen_log.jsonl").open("a")

specs = sorted(PROMPTS.glob("*.json"))
print(f"prompts: {len(specs)}", flush=True)
for sp in specs:
    p = json.loads(sp.read_text())
    pid, out_wav = p["id"], OUT / f"mm3_{p['id']}.wav"
    if out_wav.exists():
        print(f"{pid}: уже есть, пропуск", flush=True)
        continue
    cmd = [BIN, "--task", "gen", "--family", "minimax_music3",
           "--model", MODEL, "--backend", "cuda", "--metrics",
           "--text", p["caption"],
           "--request-option", f"lyrics={p['lyrics']}",
           "--request-option", f"duration_sec={p.get('duration_sec', 135)}",
           "--request-option", "num_inference_steps=15",
           "--request-option", "seed=42",
           "--out", str(out_wav)]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        gen_s = round(time.time() - t0, 1)
        ok = out_wav.exists() and out_wav.stat().st_size > 10000
        if not ok:
            print(f"ERR {pid} rc={r.returncode} stdout: {r.stdout[-300:]!r} stderr: {r.stderr[-500:]!r}", flush=True)
        (OUT / f"mm3_{pid}.log").write_text(r.stdout[-4000:] + "\n===STDERR===\n" + r.stderr[-8000:])
        rec = {"id": pid, "type": p["type"], "bpm": p["bpm"], "gen_s": gen_s,
               "ok": bool(ok), "rc": r.returncode}
    except subprocess.TimeoutExpired:
        rec = {"id": pid, "type": p["type"], "bpm": p["bpm"], "gen_s": TIMEOUT, "ok": False, "rc": "timeout"}
    log.write(json.dumps(rec) + "\n")
    log.flush()
    print(rec, flush=True)
print("done", flush=True)
