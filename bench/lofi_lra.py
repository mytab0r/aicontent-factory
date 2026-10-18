"""t_fe1fcf66: LRA сырой ACE vs мастер (LOFI_AF dynamic vs linear 2-pass), 120 с, прод-промпт + ref1.
Варианты лирики: prod "[Instrumental]" и структура с тихими секциями. Вывод: out/lra.json + mp3."""
import importlib.util, json, os, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, "pipeline")
import types; sys.modules.setdefault("gradio_client", types.SimpleNamespace(Client=None, handle_file=None))  # v1-путь не нужен
spec = importlib.util.spec_from_file_location("m03", "pipeline/03_music.py"); m03 = importlib.util.module_from_spec(spec); spec.loader.exec_module(m03)
import mastering, quality_gate as qg

OUT = Path("out"); OUT.mkdir(exist_ok=True)
REF = os.environ.get("ACE15_REF_AUDIO")
PROMPT = m03.GENRE_PROMPTS["anime lofi"]
LYR = {"prod": "[Instrumental]",
       "struct": "[Intro]\n[Instrumental]\n\n[Verse]\n[Instrumental]\n\n[Breakdown]\n[Instrumental]\n\n[Outro]\n[Instrumental]"}
SEEDS = [int(s) for s in os.environ.get("SEEDS", "11,22,33,44").split(",")]


class Lyr(m03._Http):
    def __init__(self, base, lyr):
        super().__init__(base); self.lyr = lyr
    def post(self, path, body, timeout=600):
        if path == "/release_task": body = {**body, "lyrics": self.lyr}
        return super().post(path, body, timeout)
    def post_file(self, path, body, field, fp):
        return super().post_file(path, {**body, "lyrics": self.lyr}, field, fp)


def ff(src, dst, af):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", af, "-c:a", "libmp3lame", "-b:a", "192k", str(dst)], check=True)


def linear(src, dst):
    e = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", "highpass=f=28,loudnorm=I=-14:TP=-2:LRA=50:print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
    j = json.loads(e[e.rindex("{"):e.rindex("}") + 1])
    ff(src, dst, f"highpass=f=28,loudnorm=I=-14:TP=-2:LRA=50:linear=true:measured_I={j['input_i']}:measured_LRA={j['input_lra']}:"
                 f"measured_TP={j['input_tp']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}")


def meas(p):
    why, m = qg.objective(p, "anime lofi")
    return {"i": m["i"], "lra": m["lra"], "tp": m["tp"], "bands": m["bands"], "fail": why}


rows = []
for v, lyr in LYR.items():
    api = Lyr(os.environ["ACE15_ENDPOINT"], lyr)
    for s in SEEDS:
        raw = OUT / f"{v}_s{s}_raw.mp3"
        item = m03.generate_track_v15(PROMPT, 120, s, raw, api=api, ref_audio=REF)
        dyn, lin = OUT / f"{v}_s{s}_dyn.mp3", OUT / f"{v}_s{s}_lin.mp3"
        ff(raw, dyn, mastering.LOFI_AF); linear(raw, lin)
        r = {"variant": v, "seed": s, "bpm": item.get("bpm"), "raw": meas(raw), "dyn": meas(dyn), "lin": meas(lin)}
        rows.append(r)
        print(json.dumps({k: (x["lra"] if isinstance(x, dict) else x) for k, x in r.items()}), flush=True)
        (OUT / "lra.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
print("variant seed | LRA raw / dyn(LOFI_AF) / lin | fails(lin)")
for r in rows:
    print(r["variant"], r["seed"], "|", r["raw"]["lra"], r["dyn"]["lra"], r["lin"]["lra"], "|", "; ".join(r["lin"]["fail"]) or "PASS")
