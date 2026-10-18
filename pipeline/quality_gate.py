#!/usr/bin/env python3
"""Критик трека перед публикацией (03c). exit 1 = не публиковать, шаги 04-07 не идут.

1) Объективно: динамика (LRA), 8 полос ±2 дБ и баланс мелодия/муть против одобренного владельцем эталона жанра.
   Тишина/LUFS/TP «кашу» не ловят: 16.10 на канал ушло LRA 1.4 при эталоне 10.9.
2) Модель-критик Meta audiobox-aesthetics, CE (предсказание «понравится ли»), в контейнере ace-step.
   Замеры: рефы ниши CE 7.07-7.91, брак base-модели 2.1-3.6.
Запуск: quality_gate.py [track.mp3 genre] [--no-ce] [--final]; без аргументов = последний runs/*/track.mp3.
--final (шаг 04b) = целостность mp4 (V2/V3: потоки, длительность, синхрон) + тот же объективный гейт по звуку ФИНАЛЬНОГО video.mp4 (AAC после 04 assemble), без CE:
   17.10 YouTube-копия p-kkEmLGviU дала TP +1.3..+1.9 dBTP — перекодирование добавляет пики, мерить надо то, что уходит.
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
# A6: внутренняя тишина/обрыв >= 2 с ниже -50 дБ вне хвоста (последние 10 с = штатное затухание: ref1 6.5 с, v2 3.4 с)
SIL_DB, SIL_MIN, TAIL = -50, 2.0, 10.0
# A15: интегральная громкость финального звука. YouTube нормализует к ~-14 LUFS: тише -16 = трек проигрывает
# соседям в ленте, громче -13 = срез нормализацией + пересжатие. Эталоны: ref1 -15.1, v2 -13.9 (проходят).
MIN_I, MAX_I = -16.0, -13.0
# V2/V3: финальный файл цел — есть видео- и аудиопоток, длительности потоков совпадают и равны треку ±2 %.
# 13-16.10 на канал ушли 4 ролика P0D (битая заливка) — длительность сверяется до публикации.
DUR_TOL = 0.02
# V1: чёрный экран >= 2 с в финальном видео (сбой анимации/кодирования). Порог яркости 0.10 — ночные обложки
# канала YAVG 41-88 (из 255) проходят с запасом.
BLACK_MIN = 2.0
MIN_CE = 6.5  # ниже худшего рефа ниши (7.07), сильно выше брака (<=3.6)


def ff(f, af):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-vn", "-af", af, "-f", "null", "-"],
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


def gaps(f):
    """A6: [(start, dur)] тишины внутри трека; хвост-затухание и первая секунда не считаются."""
    e = ff(f, f"silencedetect=noise={SIL_DB}dB:d={SIL_MIN}")
    h, m, x = re.findall(r"Duration: (\d+):(\d+):([\d.]+)", e)[0]
    dur = int(h) * 3600 + int(m) * 60 + float(x)
    st = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", e)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", e)] + [dur] * len(st)
    return [(round(a, 1), round(b - a, 1)) for a, b in zip(st, en) if a > 1.0 and b < dur - TAIL]


def loud_why(i):
    return [] if MIN_I <= i <= MAX_I else [f"громкость {i:+.1f} LUFS вне {MIN_I}..{MAX_I}: YouTube-нормализация"]


def objective(f, genre):
    b = [float(re.findall(r"RMS level dB: (-?[\d.]+)", ff(f, f"highpass=f={lo},highpass=f={lo},lowpass=f={hi},lowpass=f={hi},"
         "astats=measure_overall=RMS_level:measure_perchannel=none"))[-1]) for lo, hi in BANDS]
    e = ff(f, "ebur128=peak=true")
    lra = float(re.findall(r"LRA:\s+([\d.]+)", e)[-1])
    tp = float(re.findall(r"Peak:\s+(-?[\d.]+|-inf)", e)[-1].replace("-inf", "-200"))
    li = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", e)[-1])
    why = judge(b, lra, genre) + ([f"true peak {tp:+.1f} dBTP > {MAX_TP}: клиппинг"] if tp > MAX_TP else []) + loud_why(li)
    g = gaps(f)
    why += [f"тишина/обрыв {d} с на {a} с (< {SIL_DB} дБ)" for a, d in g]
    return why, {"lra": lra, "tp": tp, "i": li, "gaps": g, "bands": [round(x, 1) for x in b], "balance": round(balance(b), 1)}


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
    return ce_batch([f])[0]


def ce_batch(files):
    """t_b4006a6e: CE для списка треков ОДНИМ прогоном критика (модель грузится 1 раз).
    3 отрывка по 30 с (10/50/90 %) на трек. Возврат [[c,c,c], ...] в порядке files. Ошибка критика = FAIL."""
    td = tempfile.mkdtemp()
    subprocess.run(["docker", "exec", "ace-step", "sh", "-c", "rm -rf /app/output/qg && mkdir -p /app/output/qg/in"], check=True)
    clips = []
    for fi, f in enumerate(files):
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                   capture_output=True, text=True).stdout)
        for i, frac in enumerate((0.1, 0.5, 0.9)):
            p = f"{td}/t{fi:03d}c{i}.wav"  # имя сортируется = порядок files (AES читает sorted listdir)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(max(0.0, dur * frac - 15)), "-t", "30",
                            "-i", str(f), p], check=True)
            subprocess.run(["docker", "cp", p, "ace-step:/app/output/qg/in/"], check=True)
            clips.append(f"in/t{fi:03d}c{i}.wav")
    out = subprocess.run(["docker", "exec", "ace-step", "sh", "-c", AES], capture_output=True, text=True, timeout=1500)
    res = {l.split("\t")[0]: json.loads(l.split("\t")[1])["CE"] for l in out.stdout.splitlines() if "\t" in l}
    if sorted(res) != sorted(clips):
        raise RuntimeError(f"критик не отработал ({len(res)}/{len(clips)}): {out.stdout[-300:]} {out.stderr[-600:]}")
    return [[res[c] for c in clips[3 * i:3 * i + 3]] for i in range(len(files))]


def streams(f):
    """{codec_type: duration} + format duration из ffprobe."""
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration:format=duration",
                                   "-of", "json", str(f)], capture_output=True, text=True).stdout or "{}")
    d = {s.get("codec_type"): float(s.get("duration") or 0) for s in j.get("streams", [])}
    d["format"] = float(j.get("format", {}).get("duration") or 0)
    return d


def integrity_why(f, expect=None):
    """V2/V3: битый/пустой файл, нет потока, рассинхрон звук/видео, длительность != треку."""
    d = streams(f)
    if "video" not in d or "audio" not in d:
        return [f"нет потока: {sorted(k for k in d if k != 'format')} (нужны video+audio)"]
    v, a = d["video"] or d["format"], d["audio"] or d["format"]
    why = [] if v > 1 and a > 1 else [f"длительность 0/битый файл: видео {v:.1f} с, звук {a:.1f} с"]
    if abs(v - a) > DUR_TOL * max(v, a):
        why.append(f"рассинхрон: видео {v:.1f} с, звук {a:.1f} с")
    if expect and abs(d["format"] - expect) > DUR_TOL * expect:
        why.append(f"длительность {d['format']:.1f} с != трек {expect:.1f} с ±{DUR_TOL:.0%}")
    return why


def black_why(f):
    """V1: [причина] на каждый отрезок чёрного кадра >= BLACK_MIN с."""
    e = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-an", "-vf",
                        f"blackdetect=d={BLACK_MIN}:pix_th=0.10:pic_th=0.98", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    return [f"чёрный кадр {float(d):.1f} с с {float(a):.1f} с" for a, d in
            re.findall(r"black_start:([\d.]+) black_end:[\d.]+ black_duration:([\d.]+)", e)]


def target(d, final):
    """--final: финальный файл после 04 assemble (то, что заливается), иначе трек после 03."""
    return d / ("video.mp4" if final else "track.mp3")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    expect = None
    if args:
        f, genre = args[0], args[1]
    else:
        from common import latest_run_dir
        d = latest_run_dir()
        f, genre = target(d, "--final" in argv), json.loads((d / "music_meta.json").read_text(encoding="utf-8"))["genre"]
        if (d / "track.mp3").exists():
            expect = streams(d / "track.mp3")["format"]
    why, m = objective(f, genre)
    if "--final" in argv:
        why += integrity_why(f, expect) + black_why(f)
    if "--no-ce" not in argv and "--final" not in argv:
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
