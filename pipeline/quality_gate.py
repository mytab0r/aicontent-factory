#!/usr/bin/env python3
"""Критик трека перед публикацией (03c). exit 1 = не публиковать, шаги 04-07 не идут.

1) Объективно: динамика (LRA) и баланс 5 полос против одобренного владельцем эталона жанра.
   Тишина/LUFS/TP «кашу» не ловят: 16.10 на канал ушло LRA 1.4 при эталоне 10.9.
2) Модель-критик Meta audiobox-aesthetics, CE (предсказание «понравится ли»), в контейнере ace-step.
   Замеры: рефы ниши CE 7.07-7.91, брак base-модели 2.1-3.6.
Запуск: quality_gate.py [track.mp3 genre] [--no-ce]; без аргументов = последний runs/*/track.mp3.
"""
import json, re, subprocess, sys, tempfile

BANDS = [(20, 150), (150, 1000), (1000, 4000), (4000, 8000), (8000, 16000)]
# дБ относительно баса, сняты с одобренных эталонов: lofi = ref1 (13.10), phonk = v2 (15.10, LRA 1.5 — так одобрен).
REF = {"lofi": {"bands": [0.0, -4.2, -10.4, -18.2, -19.7], "min_lra": 5.0},
       "phonk": {"bands": [0.0, -6.1, -8.8, -13.6, -15.4], "min_lra": 0.0}}
BAND_TOL = 3.0
MIN_CE = 6.5  # ниже худшего рефа ниши (7.07), сильно выше брака (<=3.6)


def ff(f, af):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-af", af, "-f", "null", "-"],
                          capture_output=True, text=True).stderr


def objective(f, genre):
    ref = REF["phonk" if "phonk" in genre else "lofi"]
    b = [float(re.findall(r"RMS level dB: (-?[\d.]+)", ff(f, f"highpass=f={lo},lowpass=f={hi},"
         "astats=measure_overall=RMS_level:measure_perchannel=none"))[-1]) for lo, hi in BANDS]
    bands = [round(x - b[0], 1) for x in b]
    lra = float(re.findall(r"LRA:\s+([\d.]+)", ff(f, "ebur128"))[-1])
    why = [f"LRA {lra} < {ref['min_lra']}: динамика раздавлена (каша)"] if lra < ref["min_lra"] else []
    why += [f"полоса {lo}-{hi} Гц {x - r:+.1f} дБ к эталону" for (lo, hi), x, r
            in zip(BANDS, bands, ref["bands"]) if abs(x - r) > BAND_TOL]
    return why, {"lra": lra, "bands": bands}


# как bench/aes.sh (exp/vox-insert, проверено на ПК): пакеты на C: в /app/output/aes/pkgs, torch из образа
AES = r"""set -e; cd /app/output/qg; export HF_HOME=/root/.cache/huggingface PYTHONPATH=/app/output/aes/pkgs
PY=python3; for c in /app/.venv/bin/python /opt/venv/bin/python; do [ -x $c ] && { PY=$c; break; }; done
pi() { $PY -m pip install -q --target /app/output/aes/pkgs "$@" 2>/dev/null || uv pip install -q --python $PY --target /app/output/aes/pkgs "$@"; }
$PY -c "import audiobox_aesthetics" 2>/dev/null || pi --no-deps audiobox_aesthetics
for m in submitit tqdm huggingface_hub requests safetensors rich; do $PY -c "import $m" 2>/dev/null || pi $m; done
$PY -c "import json,os
from audiobox_aesthetics.infer import initialize_predictor
p=initialize_predictor(); fs=json.loads(os.environ[\"QG_CLIPS\"])
for f,s in zip(fs,p.forward([{\"path\":f} for f in fs])): print(f+chr(9)+json.dumps(s))\""""


def ce_scores(f):
    """3 отрывка по 30 с (10/50/90 % трека) -> audiobox. Ошибка критика = FAIL, не пропуск."""
    return ce_batch([f])[0]


def ce_batch(files):
    """t_b4006a6e: CE для списка треков ОДНИМ прогоном критика (модель грузится 1 раз).
    3 отрывка по 30 с (10/50/90 %) на трек. Возврат: [[c,c,c], ...] в порядке files."""
    out = _ce_run([str(f) for f in files])
    return out


def _ce_run(files):
    td = tempfile.mkdtemp()
    subprocess.run(["docker", "exec", "ace-step", "sh", "-c", "rm -rf /app/output/qg && mkdir -p /app/output/qg/in"], check=True)
    clips = []
    for fi, f in enumerate(files):
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                   capture_output=True, text=True).stdout)
        for i, frac in enumerate((0.1, 0.5, 0.9)):
            p = f"{td}/t{fi:02d}c{i}.wav"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(max(0.0, dur * frac - 15)), "-t", "30",
                            "-i", str(f), p], check=True)
            subprocess.run(["docker", "cp", p, f"ace-step:/app/output/qg/in/"], check=True)
            clips.append(f"in/{p.split('/')[-1]}")
    # список клипов через env (не инжект в код: кавычки ломают sh -c, видно на прогоне 4)
    out = subprocess.run(["docker", "exec", "ace-step", "sh", "-c",
                          f"QG_CLIPS='{json.dumps(clips)}' {AES}"],
                         capture_output=True, text=True, timeout=1500)
    res = {}
    for l in out.stdout.splitlines():
        if "\t" in l:
            k, v = l.split("\t", 1)
            res[k] = json.loads(v)["CE"]
    if sorted(res) != sorted(clips) or any(v is None for v in res.values()):
        raise RuntimeError(f"критик не отработал ({len(res)}/{len(clips)}): {out.stdout[-300:]} {out.stderr[-600:]}")
    return [[res[c] for c in clips[3 * i:3 * i + 3]] for i in range(len(files))]


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if args:
        f, genre = args[0], args[1]
    else:
        from common import latest_run_dir
        d = latest_run_dir()
        f, genre = d / "track.mp3", json.loads((d / "music_meta.json").read_text(encoding="utf-8"))["genre"]
    why, m = objective(f, genre)
    if "--no-ce" not in argv:
        try:
            ces = ce_scores(f)
            m["ce"] = [round(c, 2) for c in ces]
            if min(ces) < MIN_CE:
                why.append(f"критик audiobox: CE {min(ces):.2f} < {MIN_CE} (рефы ниши 7.1-7.9)")
        except Exception as e:  # критик недоступен -> не публикуем вслепую
            why.append(str(e)[:400])
    print(json.dumps({"track": str(f), "genre": genre, **m, "fail": why}, ensure_ascii=False))
    for w in why:
        print(f"::error::quality gate: {w}")
    return 1 if why else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
