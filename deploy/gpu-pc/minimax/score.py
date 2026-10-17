#!/usr/bin/env python3
"""Спайк t_737ca0ec: сводная таблица 10x2 (CE / PQ / время / ffmpeg-брак) + вердикт GO/KILL.
CE/PQ — Meta audiobox-aesthetics ВНУТРИ контейнера ace-step (как pipeline/quality_gate.py).
Брак — internal silence (>=3 c), TP > -1 dBTP, длительность < 90 c. Python3 stdlib."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "spike-out")
ACE = os.environ.get("ACE_CONTAINER", "ace-step")
BRAK_DUR_MIN = 90.0

AES = r"""set -e; cd /app/output/qg; export HF_HOME=/root/.cache/huggingface PYTHONPATH=/app/output/aes/pkgs
PY=python3; for c in /app/.venv/bin/python /opt/venv/bin/python; do [ -x $c ] && { PY=$c; break; }; done
pi() { $PY -m pip install -q --target /app/output/aes/pkgs "$@" 2>/dev/null || uv pip install -q --python $PY --target /app/output/aes/pkgs "$@"; }
$PY -c "import audiobox_aesthetics" 2>/dev/null || pi --no-deps audiobox_aesthetics
for m in submitit tqdm huggingface_hub requests safetensors rich; do $PY -c "import $m" 2>/dev/null || pi $m; done
$PY -c '
import json,os
from audiobox_aesthetics.infer import initialize_predictor
p=initialize_predictor(); fs=sorted("in/"+f for f in os.listdir("in"))
for f,s in zip(fs,p.forward([{"path":f} for f in fs])): print(f+chr(9)+json.dumps(s))'"""


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def dur_sec(f):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)])
    return float(r.stdout.strip())


def brak(f, dur):
    """ffmpeg-брак: список причин."""
    why = []
    if dur < BRAK_DUR_MIN:
        why.append(f"длительность {dur:.0f}с < 90с")
    s = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-vn",
            "-af", "silencedetect=noise=-40dB:d=3", "-f", "null", "-"]).stderr
    for t in (float(x) for x in re.findall(r"silence_start: ([\d.]+)", s)):
        if t < dur - 5:  # хвостовая тишина — норма
            why.append(f"тишина от {t:.0f}с")
            break
    e = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"]).stderr
    lra = re.findall(r"LRA:\s+([\d.]+)", e)
    tp = re.findall(r"Peak:\s+(-?[\d.]+|-inf)", e)
    if lra:
        why.append(f"LRA {lra[-1]}")
    if tp and tp[-1] != "-inf" and float(tp[-1]) > -1.0:
        why.append(f"TP {tp[-1]} dBTP клиппинг")
    return why


def ce_pq(files):
    """audiobox в ace-step: 3 отрывка (10/50/90%, 30 c) на файл. -> {file: {CE,PQ,...}}"""
    sh(["docker", "exec", ACE, "sh", "-c", "rm -rf /app/output/qg && mkdir -p /app/output/qg/in"], check=True)
    names = []
    td = tempfile.mkdtemp()
    for i, f in enumerate(files):
        d = dur_sec(f)
        for j, frac in enumerate((0.1, 0.5, 0.9)):
            c = f"{td}/t{i:03d}c{j}.wav"
            sh(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(max(0.0, d * frac - 15)), "-t", "30",
                "-i", str(f), c], check=True)
            sh(["docker", "cp", c, f"{ACE}:/app/output/qg/in/"], check=True)
            names.append(f"in/t{i:03d}c{j}.wav")
    r = sh(["docker", "exec", ACE, "sh", "-c", AES], timeout=2400)
    if r.returncode != 0:
        raise SystemExit(f"audiobox упал: {r.stderr[-1500:]}")
    res = {}
    for line in r.stdout.splitlines():
        if "\t" not in line:
            continue
        k, v = line.split("\t", 1)
        res[k] = json.loads(v)
    missing = [n for n in names if n not in res]
    if missing:
        raise SystemExit(f"audiobox не отдал {len(missing)} отрывков: {missing[:5]} {r.stderr[-500:]}")
    agg = {}
    for i, f in enumerate(files):
        cs = [res[n] for n in names[3 * i:3 * i + 3]]
        agg[str(f)] = {k: round(sum(c[k] for c in cs) / len(cs), 2) for k in cs[0]}
    return agg


def main():
    mm_log = {json.loads(l)["id"]: json.loads(l) for l in (OUT / "gen_log.jsonl").read_text().splitlines() if l.strip()}
    ace_log = {json.loads(l)["id"]: json.loads(l) for l in (OUT / "ace_gen_log.jsonl").read_text().splitlines() if l.strip()}
    mm = sorted(OUT.glob("mm3_*.wav"))
    ace = sorted(OUT.glob("ace/ace_*.mp3"))
    if not mm or not ace:
        raise SystemExit(f"нет треков: mm3={len(mm)} ace={len(ace)}")
    scores = ce_pq(mm + ace)
    rows = []
    for sp in sorted((Path("deploy/gpu-pc/minimax/prompts")).glob("*.json")):
        p = json.loads(sp.read_text())
        row = {"id": p["id"], "type": p["type"], "bpm": p["bpm"]}
        for tag, f, lg in (("mm3", OUT / f"mm3_{p['id']}.wav", mm_log.get(p["id"])),
                           ("ace", OUT / "ace" / f"ace_{p['id']}.mp3", ace_log.get(p["id"]))):
            if not f.exists() or not lg or not lg.get("ok"):
                row[tag] = {"fail": "нет трека или генерация упала", "gen_s": lg and lg.get("gen_s")}
                continue
            d = dur_sec(f)
            s = scores[str(f)]
            row[tag] = {"dur_s": round(d), "gen_s": lg["gen_s"], "CE": s["CE"], "PQ": s["PQ"],
                        "brak": "; ".join(brak(f, d))}
        rows.append(row)

    def agg(tag, key):
        v = [r[tag][key] for r in rows if isinstance(r[tag], dict) and key in r[tag]]
        return round(sum(v) / len(v), 2) if v else None

    mm_pq, ace_pq = agg("mm3", "PQ"), agg("ace", "PQ")
    mm_ce, ace_ce = agg("mm3", "CE"), agg("ace", "CE")
    ratios = [r["mm3"]["gen_s"] / r["ace"]["gen_s"] for r in rows
              if isinstance(r["mm3"], dict) and isinstance(r["ace"], dict)
              and "gen_s" in r["mm3"] and "gen_s" in r["ace"] and r["ace"]["gen_s"] > 0]
    t_ratio = round(sum(ratios) / len(ratios), 1) if ratios else None
    mm_max = max((r["mm3"]["gen_s"] for r in rows if isinstance(r["mm3"], dict) and "gen_s" in r["mm3"]), default=None)

    verdict, why = "KILL", []
    over_5min = any(isinstance(r["mm3"], dict) and r["mm3"].get("dur_s", 120) and r["mm3"]["gen_s"] > 300 for r in rows)
    if mm_pq is None or ace_pq is None:
        why.append("нет полных данных (генерации упали)")
    else:
        pq_gain = (mm_pq - ace_pq) / ace_pq
        if pq_gain >= 0.10 and t_ratio is not None and t_ratio <= 3.0:
            verdict = "GO"
        elif pq_gain >= 0.10 and t_ratio is not None and t_ratio > 3.0 and not over_5min:
            why.append(f"качество +{pq_gain:.0%}, но время {t_ratio}x ACE-Step (>3x) — GO по правилам невозможен")
        else:
            why.append(f"качество PQ {mm_pq} vs {ace_pq} ({pq_gain:+.0%} < +10%)")
        if over_5min:
            why.append("трек генерировался >5 мин")
        why.append("лицензия MiniMax-Music3-Community: коммерция бесплатна до $20M выручки, в UI сервиса обязательна пометка «MiniMax-Music3»; для YouTube — метка synthetic content")

    md = ["# Спайк MiniMax Music 3 vs ACE-Step 1.5 turbo (RTX 5070 12GB, t_737ca0ec)", "",
          "MiniMax: форк fspecii/audio.cpp-lowend-gpu @3f593a3, GGUF q4_k (LM/transformer) + rvq q8_0, 15 шагов, seed 42.",
          "ACE-Step: контейнерный слот 1.5 (turbo), REST, seed 41+id. Треки 120 с. Метрики: audiobox-aesthetics (среднее 3x30с), ffmpeg (LRA/TP/silence).",
          "", "| id | тип | BPM | MiniMax: t,c / CE / PQ / брак | ACE: t,c / CE / PQ / брак | время x |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        def cell(tag):
            c = r[tag]
            if not isinstance(c, dict) or "CE" not in c:
                return str(c.get("fail", "?") if isinstance(c, dict) else c)
            return f"{c['dur_s']}с / {c['gen_s']}с / {c['CE']} / {c['PQ']} / {c['brak'] or '—'}"
        tr = ""
        if isinstance(r["mm3"], dict) and isinstance(r["ace"], dict) and "gen_s" in r["mm3"] and "gen_s" in r["ace"]:
            tr = f"{r['mm3']['gen_s'] / r['ace']['gen_s']:.1f}x"
        md.append(f"| {r['id']} | {r['type']} | {r['bpm']} | {cell('mm3')} | {cell('ace')} | {tr} |")
    md += ["", f"**Среднее PQ:** MiniMax {mm_pq} vs ACE {ace_pq}; **CE:** {mm_ce} vs {ace_ce}; **время:** {t_ratio}x ACE; макс. генерация MiniMax {mm_max}с.",
           "", f"## Вердикт: {verdict}"]
    md += [f"- {w}" for w in why]
    (OUT / "minimax_vs_ace_results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    import csv
    with (OUT / "minimax_vs_ace_results.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "type", "bpm", "model", "dur_s", "gen_s", "CE", "PQ", "brak"])
        for r in rows:
            for tag in ("mm3", "ace"):
                c = r[tag]
                w.writerow([r["id"], r["type"], r["bpm"], tag,
                            c.get("dur_s", ""), c.get("gen_s", ""), c.get("CE", ""), c.get("PQ", ""),
                            c.get("fail", c.get("brak", "")) if isinstance(c, dict) else ""])
    print("\n".join(md))
    if verdict == "KILL":
        print("VERDICT=KILL (файлы результатов записаны; контейнер/веса MiniMax подлежат удалению)")
    else:
        print("VERDICT=GO")


if __name__ == "__main__":
    main()
