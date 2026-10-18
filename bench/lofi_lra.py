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


def gain(src, dst):
    """Чистое усиление до -14 LUFS + лимитер -3 dB (без loudnorm): LRA не трогается, кроме пиков."""
    e = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", "highpass=f=28,ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    i = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", e)[-1])
    ff(src, dst, f"highpass=f=28,volume={-14 - i:.2f}dB,alimiter=limit=0.708:attack=5:release=50:level=disabled")


def meas(p):
    why, m = qg.objective(p, "anime lofi")
    return {"i": m["i"], "lra": m["lra"], "tp": m["tp"], "bands": m["bands"], "fail": why}


rows = []
if REF and Path(REF).is_file():
    rows.append({"variant": "ref_clip", "seed": 0, "raw": meas(REF)})
    print("ref clip", rows[-1]["raw"], flush=True)
# (вариант, лирика, длительность, seeds): 120 с = как сэмплы; 600 с = как прод-сегмент час-микса
# BENCH_PLAN="prod600:600:22,33,44" — точечный догон без повторных генераций
raw_plan = os.environ.get("BENCH_PLAN", "")
if raw_plan:
    vname, vdur, vseeds = raw_plan.split(":")
    PLAN = [(vname, LYR["prod"], int(vdur), [int(x) for x in vseeds.split(",")])]
for v, lyr, dur, seeds in PLAN:
    api = Lyr(os.environ["ACE15_ENDPOINT"], lyr)
    for s in seeds:
        raw = OUT / f"{v}_s{s}_raw.mp3"
        item = m03.generate_track_v15(PROMPT, dur, s, raw, api=api, ref_audio=REF)
        dyn, lin = OUT / f"{v}_s{s}_dyn.mp3", OUT / f"{v}_s{s}_lin.mp3"
        gn = OUT / f"{v}_s{s}_gain.mp3"
        ff(raw, dyn, mastering.LOFI_AF); linear(raw, lin); gain(raw, gn)
        r = {"variant": v, "seed": s, "bpm": item.get("bpm"), "raw": meas(raw), "dyn": meas(dyn), "lin": meas(lin), "gain": meas(gn)}
        rows.append(r)
        print(json.dumps({k: (x["lra"] if isinstance(x, dict) else x) for k, x in r.items()}), flush=True)
        (OUT / "lra.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
print("variant seed | LRA raw / dyn(LOFI_AF) / lin / gain | fails(dyn) || fails(gain)")
for r in rows[1:] if rows and rows[0]["variant"] == "ref_clip" else rows:
    print(r["variant"], r["seed"], "|", r["raw"]["lra"], r["dyn"]["lra"], r["lin"]["lra"], r["gain"]["lra"], "|",
          "; ".join(r["dyn"]["fail"]) or "PASS", "||", "; ".join(r["gain"]["fail"]) or "PASS")
