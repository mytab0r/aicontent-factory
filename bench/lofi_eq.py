"""t_fe1fcf66: 180 с сегменты (как прод после #83) проваливают гейт полос: середина +2..5 дБ.
Генерим N сегментов один раз, мастерим несколькими EQ-цепочками, считаем PASS гейта (quality_gate.judge)."""
import importlib.util, json, os, subprocess, sys, types
from pathlib import Path
sys.path.insert(0, "pipeline")
sys.modules.setdefault("gradio_client", types.SimpleNamespace(Client=None, handle_file=None))
spec = importlib.util.spec_from_file_location("m03", "pipeline/03_music.py"); m03 = importlib.util.module_from_spec(spec); spec.loader.exec_module(m03)
import mastering, quality_gate as qg

OUT = Path("out"); OUT.mkdir(exist_ok=True)
REF = os.environ.get("ACE15_REF_AUDIO")
SEEDS = [int(s) for s in os.environ.get("SEEDS", "101,202,303,404,505").split(",")]
LN = "loudnorm=I=-14:TP=-2:LRA=11"
CHAINS = {
    "base": mastering.LOFI_AF,
    "mid3": f"highpass=f=28,equalizer=f=1000:t=o:w=2:g=-3,{LN}",
    "mid4": f"highpass=f=28,equalizer=f=900:t=o:w=2.5:g=-4,{LN}",
    "bass3": f"highpass=f=28,bass=g=3:f=110,{LN}",
    "combo": f"highpass=f=28,bass=g=2:f=110,equalizer=f=1000:t=o:w=2:g=-2.5,{LN}",
    "combo2": f"highpass=f=28,bass=g=2.5:f=110,equalizer=f=300:t=o:w=1:g=-1.5,equalizer=f=1200:t=o:w=2:g=-3,{LN}",
}


def ff(src, dst, af):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", af, "-c:a", "libmp3lame", "-b:a", "192k", str(dst)], check=True)


rows = []
for s in SEEDS:
    raw = OUT / f"s{s}_raw.mp3"
    try:
        m03.generate_track_v15(m03.GENRE_PROMPTS["anime lofi"], m03.MIX_SEG_SEC, s, raw, ref_audio=REF)
    except Exception as e:  # ace-step иногда падает: сегмент пропускаем, остальные меряем
        print("gen fail", s, e, flush=True); continue
    r = {"seed": s}
    for name, af in CHAINS.items():
        p = OUT / f"s{s}_{name}.mp3"; ff(raw, p, af)
        why, m = qg.objective(str(p), "anime lofi")
        r[name] = {"lra": m["lra"], "fail": why}
    rows.append(r)
    print(json.dumps({k: (v if k == "seed" else [v["lra"], len(v["fail"])]) for k, v in r.items()}, ensure_ascii=False), flush=True)
    (OUT / "eq.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
print("chain | PASS / N | fails")
for name in CHAINS:
    ok = sum(not r[name]["fail"] for r in rows)
    print(f"RESULT {name} | {ok}/{len(rows)} | " + " || ".join("; ".join(r[name]["fail"]) or "PASS" for r in rows), flush=True)
