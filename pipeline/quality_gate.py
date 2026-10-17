#!/usr/bin/env python3
"""Критик трека перед публикацией (03c). exit 1 = не публиковать, шаги 04-07 не идут.

1) Объективно: динамика (LRA), 8 полос ±2 дБ и баланс мелодия/муть против одобренного владельцем эталона жанра.
   Тишина/LUFS/TP «кашу» не ловят: 16.10 на канал ушло LRA 1.4 при эталоне 10.9.
2) Модель-критик Meta audiobox-aesthetics, CE (предсказание «понравится ли»), в контейнере ace-step.
   Замеры: рефы ниши CE 7.07-7.91, брак base-модели 2.1-3.6.
Запуск: quality_gate.py [track.mp3 genre] [--no-ce]; без аргументов = последний runs/*/track.mp3.
"""
import json, re, subprocess, sys, tempfile

BANDS = [(20, 60), (60, 150), (150, 400), (400, 1000), (1000, 2500), (2500, 5000), (5000, 10000), (10000, 16000)]
# Абсолютные RMS дБ по полосам (двойные фильтры), сняты с одобренных эталонов целиком:
# lofi = ref1 (13.10), phonk = v2 gated (15.10, LRA 1.5 — так одобрен). Сравнение — относительно полосы 60-150 (бас).
# 5 широких полос ±3 дБ пропустили провал мелодии 1-5 кГц и муть 150-400 (p-kkEmLGviU, 17.10) — отсюда 8 полос ±2 и баланс.
REF = {"lofi": {"bands": [-26.3, -23.0, -29.6, -28.9, -33.2, -39.9, -40.2, -44.1], "min_lra": 5.0},
       "phonk": {"bands": [-23.1, -22.3, -31.3, -28.3, -30.3, -33.2, -34.2, -38.2], "min_lra": 0.0}}
BAND_TOL = 2.0
BAL_TOL = 2.0
MAX_TP = -1.0  # true peak dBTP; 17.10 YouTube-копия p-kkEmLGviU: +1.3..+1.9 = клиппинг  # (среднее 1-5 кГц) - (150-400 Гц) не хуже эталона более чем на столько
MIN_CE = 6.5  # ниже худшего рефа ниши (7.07), сильно выше брака (<=3.6)


def ff(f, af):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-af", af, "-f", "null", "-"],
                          capture_output=True, text=True).stderr


def rel(b):
    return [x - b[1] for x in b]


def balance(b):
    return (b[4] + b[5]) / 2 - b[2]


def judge(bands, lra, genre):
    """bands = абсолютные RMS дБ по BANDS. Возвращает список причин FAIL."""
    ref = REF["phonk" if "phonk" in genre else "lofi"]
    why = [f"LRA {lra} < {ref['min_lra']}: динамика раздавлена (каша)"] if lra < ref["min_lra"] else []
    why += [f"полоса {lo}-{hi} Гц {x - r:+.1f} дБ к эталону" for (lo, hi), x, r
            in zip(BANDS, rel(bands), rel(ref["bands"])) if abs(x - r) > BAND_TOL]
    d = balance(bands) - balance(ref["bands"])
    if d < -BAL_TOL:
        why.append(f"баланс мелодия(1-5 кГц) - муть(150-400 Гц) {d:+.1f} дБ к эталону: лид утоплен")
    return why


def objective(f, genre):
    b = [float(re.findall(r"RMS level dB: (-?[\d.]+)", ff(f, f"highpass=f={lo},highpass=f={lo},lowpass=f={hi},lowpass=f={hi},"
         "astats=measure_overall=RMS_level:measure_perchannel=none"))[-1]) for lo, hi in BANDS]
    e = ff(f, "ebur128=peak=true")
    lra = float(re.findall(r"LRA:\s+([\d.]+)", e)[-1])
    tp = float(re.findall(r"Peak:\s+(-?[\d.]+|-inf)", e)[-1].replace("-inf", "-200"))
    why = judge(b, lra, genre) + ([f"true peak {tp:+.1f} dBTP > {MAX_TP}: клиппинг"] if tp > MAX_TP else [])
    return why, {"lra": lra, "tp": tp, "bands": [round(x, 1) for x in b], "balance": round(balance(b), 1)}


# как bench/aes.sh (exp/vox-insert, проверено на ПК): пакеты на C: в /app/output/aes/pkgs, torch из образа
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


def ce_scores(f):
    """3 отрывка по 30 с (10/50/90 % трека) -> audiobox. Ошибка критика = FAIL, не пропуск."""
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                               capture_output=True, text=True).stdout)
    td = tempfile.mkdtemp()
    subprocess.run(["docker", "exec", "ace-step", "sh", "-c", "rm -rf /app/output/qg && mkdir -p /app/output/qg/in"], check=True)
    for i, frac in enumerate((0.1, 0.5, 0.9)):
        p = f"{td}/c{i}.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(max(0.0, dur * frac - 15)), "-t", "30",
                        "-i", str(f), p], check=True)
        subprocess.run(["docker", "cp", p, "ace-step:/app/output/qg/in/"], check=True)
    out = subprocess.run(["docker", "exec", "ace-step", "sh", "-c", AES], capture_output=True, text=True, timeout=1500)
    ces = [json.loads(l.split("\t")[1])["CE"] for l in out.stdout.splitlines() if "\t" in l]
    if len(ces) != 3:
        raise RuntimeError(f"критик не отработал: {out.stdout[-300:]} {out.stderr[-600:]}")
    return ces


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
