#!/usr/bin/env python3
"""Критик трека перед публикацией (03c). exit 1 = не публиковать, шаги 04-07 не идут.

1) Объективно: динамика (LRA), 8 полос ±2 дБ и баланс мелодия/муть против одобренного владельцем эталона жанра.
   Тишина/LUFS/TP «кашу» не ловят: 16.10 на канал ушло LRA 1.4 при эталоне 10.9.
2) Модель-критик Meta audiobox-aesthetics, CE (предсказание «понравится ли»), в контейнере ace-step.
   Замеры: рефы ниши CE 7.07-7.91, брак base-модели 2.1-3.6.
Запуск: quality_gate.py [track.mp3 genre] [--no-ce] [--final] [--seams=t1,t2] | --video [run_dir] (P19); без аргументов = последний runs/*/track.mp3.
--final (шаг 04b) = целостность mp4 (V2/V3: потоки, длительность, синхрон) + тот же объективный гейт и CE по окнам/стыкам ФИНАЛЬНОГО video.mp4 (AAC после 04 assemble):
   17.10 YouTube-копия p-kkEmLGviU дала TP +1.3..+1.9 dBTP — перекодирование добавляет пики, мерить надо то, что уходит.
"""
import json, os, re, subprocess, sys, tempfile

BANDS = [(20, 60), (60, 150), (150, 400), (400, 1000), (1000, 2500), (2500, 5000), (5000, 10000), (10000, 16000)]
# Абсолютные RMS дБ по полосам (двойные фильтры), сняты с одобренных эталонов целиком:
# lofi = ref1 (13.10), phonk = v2 gated (15.10, LRA 1.5 — так одобрен). Сравнение — относительно полосы 60-150 (бас).
# 5 широких полос ±3 дБ пропустили провал мелодии 1-5 кГц и муть 150-400 (p-kkEmLGviU, 17.10) — отсюда 8 полос ±2 и баланс.
# t_ef393676 (калибровка по разметке владельца 20.10, owners_labels.py): ab_1 (LRA 3.7, полоса
# 400-1000 Гц +2.4 дБ) ОДОБРЕН владельцем — min_lra 5.0 давил одобренное (0 выпусков), полосы
# ±2.0 тоже. Новые пороги: min_lra 3.5 (одобренный минимум 3.7, запас 0.2), полоса ±3.0, но FAIL
# только если хоть одна полоса >5.0 ИЛИ сумма мягких >8.0 (одобренный versija_1 даёт 4.7+3.0=7.7). Жалобы ловятся: p-kkEmLGviU 150-400 Гц +11.0, tIJKpWrVzOM +9.7,
# баланс мелодия/муть не тронут (одобренные ±1.5, жалобы -4.7..-11.4). LRA мерится файлом целиком:
# на 30-с голове ab_3 1.2 против 5.4 полного — 30-с сэмпл непоказателен (замер 21.10).
REF = {"lofi": {"bands": [-26.3, -23.0, -29.6, -28.9, -33.2, -39.9, -40.2, -44.1], "min_lra": 3.5},
       "phonk": {"bands": [-23.1, -22.3, -31.3, -28.3, -30.3, -33.2, -34.2, -38.2], "min_lra": 0.0}}
BAND_TOL = 3.0   # мягкое отклонение полосы
BAND_MAX = 5.0   # жёсткое: одиночная полоса дальше = FAIL
BAND_SOFT_SUM = 8.0  # сумма мягких отклонений (одобренный versija_1 даёт 7.7, жалобы 14.9+)
BAL_TOL = 2.0
MAX_TP = -1.0  # true peak dBTP; 17.10 YouTube-копия p-kkEmLGviU: +1.3..+1.9 = клиппинг  # (среднее 1-5 кГц) - (150-400 Гц) не хуже эталона более чем на столько
# A6: внутренняя тишина/обрыв >= 2 с ниже -50 дБ вне хвоста (последние 10 с = штатное затухание: ref1 6.5 с, v2 3.4 с)
SIL_DB, SIL_MIN, TAIL = -50, 2.0, 10.0
# A15: интегральная громкость финального звука. YouTube нормализует к ~-14 LUFS: тише -16 = трек проигрывает
# соседям в ленте, громче -13 = срез нормализацией + пересжатие. Эталоны: ref1 -15.1, v2 -13.9 (проходят).
MIN_I, MAX_I = -16.0, -13.0
# t_3ce908a7: единая цель loudnorm для всех путей рендера (mastering, shorts, речевые) — гейт и цель из одного места.
LUFS_TARGET = -14.0
# V2/V3: финальный файл цел — есть видео- и аудиопоток, длительности потоков совпадают и равны треку ±2 %.
# 13-16.10 на канал ушли 4 ролика P0D (битая заливка) — длительность сверяется до публикации.
DUR_TOL = 0.02
# V1: чёрный экран >= 2 с в финальном видео (сбой анимации/кодирования). Порог яркости 0.10 — ночные обложки
# канала YAVG 41-88 (из 255) проходят с запасом.
BLACK_MIN = 2.0
# A16: резкий конец трека (обрыв без затухания) = щелчок в конце и при повторе в плеере. Последние 0.5 с
# по RMS должны быть тише всего трека минимум на END_DROP дБ. Замер 19.10: одобренные ref1/ref2/ref3 -45.6..-46.5,
# phonk v2 -49.5, 15-мин микс ref-style6 -28.7, MIX ref-style4 -20.0; обрезанные 60-с отрывки -1.9/+1.1.
# Начало не проверяется: эталоны стартуют сразу на полной громкости (первые 100 мс ref1 -11.3 дБ).
END_WIN, END_DROP = 0.5, 12.0
# A9: моно-совместимость. Потери громкости при сведении в моно (L+R)/2 против стерео > MONO_LOSS дБ = каналы
# в противофазе (корреляция < 0): на телефоне/колонке-моно трек «пропадает». Замер 19.10: ref1/ref2/ref3 -0.3,
# phonk v2 -0.5, v1 -1.4, прод KXNsSx2FlXA -0.6; некоррелированные каналы = -3, инверсия канала = -inf.
MONO_LOSS = 3.0
# A17: инфразвук < 20 Гц и DC-смещение съедают запас громкости (loudnorm/TP), на телефонах «бубнит».
# Энергия ниже 20 Гц (двойной lowpass) относительно всего трека. Замер 19.10: ref1 -33.6, ref2 -35.5, ref3 -35.1,
# phonk v1 -27.2, v2 -31.6, v3 -25.6 (худший одобренный); брак ref1 + синус 8 Гц 0.1 = -8.4, ref1 + DC 0.05 = -10.6.
SUB_MAX = -20.0
# A18: скачок громкости между сегментами часового микса — зритель крутит громкость. Медиана short-term LUFS (3 с)
# по блокам JUMP_BLOCK с (без первых 3 с и хвоста 10 с), скачок между соседними блоками > JUMP_MAX = FAIL.
# Замер 19.10: одобренные миксы ref-style6 15 мин 1.5, ref-style4 MIX 0.8, MIX 85-95-105 1.0, voice-in-transitions 0.2.
# Блок 30 с непригоден: ref1 внутри 2-мин трека прыгает на 8.8 (штатная динамика), 60 с сглаживает её.
JUMP_BLOCK, JUMP_MAX = 60.0, 4.0
# A19: строй плывёт между частями микса (аудит 11.10 4HB26c4yow0: куски +0.05..+0.40 полутона = «фальшивые ноты»).
# Строй окна TUNE_WIN с = круговое среднее отклонения пиков спектра 100-2000 Гц от сетки A440 (центы, вес = амплитуда).
# Разброс строя между окнами > TUNE_MAX центов = FAIL. Замер 19.10 (окна 30 с): ref1 1.8, ref2 1.1, ref3 2.5,
# одобренный 15-мин микс ref-style6 6.6, MIX 85-95-105 4.2, two-formats S1-U2 0.7-2.5; брак ref1 + та же часть +40 центов = 42.
TUNE_WIN, TUNE_MAX = 30.0, 20.0
# t_b4e407ca: окно без строя (шум, перкуссия) даёт случайный угол — CI case_a (шум) ловил «разброс 21-24 центов».
# Окно в счёт, только если пики согласованы: |sum b*e^(i*phi)| / sum b >= TUNE_MIN_R. Замер: белый/розовый/коричневый
# шум 0.002-0.02, ref1 0.33-0.49, синус 1.0.
TUNE_MIN_R = 0.1
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
    dev = [x - r for x, r in zip(rel(bands), rel(ref["bands"]))]
    soft = [abs(x) for x in dev if abs(x) > BAND_TOL]
    if soft and (max(soft) > BAND_MAX or sum(soft) > BAND_SOFT_SUM):
        why += [f"полоса {lo}-{hi} Гц {x:+.1f} дБ к эталону" for (lo, hi), x in zip(BANDS, dev) if abs(x) > BAND_TOL]
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


def bands(f):
    """Абсолютные RMS дБ по BANDS (двойные фильтры). Пустая полоса (-inf) = -120."""
    return [float(re.findall(r"RMS level dB: (-?[\d.]+|-inf)", ff(f, f"highpass=f={lo},highpass=f={lo},lowpass=f={hi},lowpass=f={hi},"
            "astats=measure_overall=RMS_level:measure_perchannel=none"))[-1].replace("-inf", "-120")) for lo, hi in BANDS]


def objective(f, genre):
    b = bands(f)
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


# t_3f0f7b91 (жалоба 18.10 на p-kkEmLGviU: «первые секунды классные, потом непонятные звуки»): CE мерился по 3
# отрывкам (10/50/90 %) = 90 с из 3374 с; сегменты 600 с разваливались к концу, стыки без кроссфейда.
# Теперь: R1 CE по КАЖДОМУ окну 30 с; R2 дрейф median(CE после 60 с) ниже CE первых 60 с > 0.5;
# R3 окно ±5 с у каждого стыка проходит R1, RMS слева/справа отличается <= 3 дБ. Пороги не снижать.
WIN, DRIFT_HEAD, DRIFT_MAX, SEAM_HALF, SEAM_RMS_MAX = 30.0, 60.0, 0.5, 5.0, 3.0


def windows(dur, win=WIN):
    """Окна (start, length) подряд от 0; остаток < win = последнее окно, выровненное по концу."""
    if dur <= win:
        return [(0.0, dur)]
    w = [(i * win, win) for i in range(int(dur // win))]
    return w + ([(dur - win, win)] if dur - w[-1][0] - win > 1e-6 else [])


def ce_why(wins):
    """wins = [(start, CE)]. R1 любое окно < MIN_CE, R2 дрейф хвоста от первых 60 с > DRIFT_MAX."""
    if not wins:
        return ["R5 критик не вернул ни одного окна"]
    bad = [(s, c) for s, c in wins if c < MIN_CE]
    why = [f"R1 CE < {MIN_CE} в {len(bad)}/{len(wins)} окнах по {WIN:.0f} с, min {min(c for _, c in wins):.2f}: "
           + ", ".join(f"{s:.0f}с={c:.2f}" for s, c in bad[:10])] if bad else []
    # R2 только по сетке WIN: окно остатка, выровненное по концу, дублирует хвост и удваивает его вес
    # (ref1 120 с: окна 90 и 90.024 = одно и то же, дрейф 0.63 вместо 0.43). R1 видит все окна.
    grid = [(s, c) for s, c in wins if abs(s / WIN - round(s / WIN)) < 1e-6]
    head = [c for s, c in grid if s < DRIFT_HEAD]
    tail = sorted(c for s, c in grid if s >= DRIFT_HEAD)
    if head and tail:
        h, t = sum(head) / len(head), (tail[(len(tail) - 1) // 2] + tail[len(tail) // 2]) / 2
        if h - t > DRIFT_MAX + 1e-9:
            why.append(f"R2 дрейф: median CE после {DRIFT_HEAD:.0f} с {t:.2f} ниже первых {DRIFT_HEAD:.0f} с {h:.2f} "
                       f"на {h - t:.2f} > {DRIFT_MAX}")
    return why


def seam_why(seams):
    """R3: стык = окно ±SEAM_HALF проходит R1 и RMS слева/справа отличается не больше SEAM_RMS_MAX дБ."""
    why = []
    for x in seams:
        if x["ce"] < MIN_CE:
            why.append(f"R3 стык {x['t']:.1f} с: CE {x['ce']:.2f} < {MIN_CE}")
        if abs(x["rms_l"] - x["rms_r"]) > SEAM_RMS_MAX + 1e-9:
            why.append(f"R3 стык {x['t']:.1f} с: RMS {x['rms_l']:.1f} -> {x['rms_r']:.1f} дБ, разрыв > {SEAM_RMS_MAX}")
    return why


def duration(f):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                capture_output=True, text=True).stdout)


def tp_of(f) -> float:
    """True peak файла (ebur128=peak=true), дБТП; -inf -> -200."""
    e = ff(f, "ebur128=peak=true")
    return float(re.findall(r"Peak:\s+(-?[\d.]+|-inf)", e)[-1].replace("-inf", "-200"))


def encode_aac_tp(src, dst, bitrate: str, tp_max: float, tries: int = 5) -> float:
    """t_f5e84e62: AAC-кодер поднимает true peak ПОСЛЕ лимитера — лимитер овершут кодера не видит.
    Замер: WAV TP -1.5 -> +0.1 dBTP после aac 192k (фикстура click/noise), 04b run 40408005493 -3.7 -> +6.5.
    Поэтому меряем ЗАКОДИРОВАННЫЙ звук и опускаем потолок лимитера, пока TP <= tp_max; mux потом -c:a copy.
    Не сошлось = исключение (не молча: иначе гейт ловит клиппинг уже после заливки)."""
    limit, tp = tp_max - 0.5, None
    for _ in range(tries):
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(src),
                        "-af", f"alimiter=limit={limit:.2f}dB:level=false",
                        "-c:a", "aac", "-b:a", bitrate, str(dst)], check=True)
        tp = tp_of(dst)
        if tp <= tp_max:
            return tp
        limit -= tp - tp_max + 0.5
    raise RuntimeError(f"AAC true peak {tp:+.1f} dBTP > {tp_max} после {tries} проходов: {dst}")


def cut(f, start, length, out):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(max(0.0, start)), "-t", str(length), "-i", str(f),
                    "-vn", "-c:a", "pcm_s16le", str(out)], check=True)
    return str(out)


def rms_db(f, start, dur):
    e = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(max(0.0, start)), "-t", str(dur), "-i", str(f),
                        "-vn", "-af", "astats=measure_overall=RMS_level:measure_perchannel=none", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    return float((re.findall(r"RMS level dB: (-?[\d.]+|-inf)", e) or ["-200"])[-1].replace("-inf", "-200"))


def critic_clips(paths):
    """Реальный критик: CE для каждого wav ОДНИМ прогоном audiobox в контейнере ace-step (модель грузится 1 раз)."""
    names = []
    with tempfile.TemporaryDirectory() as td:  # t_3c6b9f04: копии wav не копятся в /tmp
        for i, p in enumerate(paths):  # имя сортируется = порядок paths (AES читает sorted listdir)
            names.append(f"c{i:05d}.wav")
            subprocess.run(["cp", str(p), f"{td}/{names[-1]}"], check=True)
        subprocess.run(["docker", "exec", "ace-step", "sh", "-c", "rm -rf /app/output/qg && mkdir -p /app/output/qg"], check=True)
        subprocess.run(["docker", "cp", f"{td}/.", "ace-step:/app/output/qg/in"], check=True)
    out = subprocess.run(["docker", "exec", "ace-step", "sh", "-c", AES], capture_output=True, text=True, timeout=3000)
    res = {l.split("\t")[0]: json.loads(l.split("\t")[1])["CE"] for l in out.stdout.splitlines() if "\t" in l}
    want = ["in/" + n for n in names]
    if sorted(res) != sorted(want):
        raise RuntimeError(f"критик не отработал ({len(res)}/{len(want)}): {out.stdout[-300:]} {out.stderr[-600:]}")
    return [res[n] for n in want]


def _critic(paths, critic):
    ce = (critic or critic_clips)(paths)  # critic_clips ищется в момент вызова (тесты подменяют)
    if len(ce) != len(paths):
        raise RuntimeError(f"критик вернул {len(ce)}/{len(paths)} оценок")
    return [float(c) for c in ce]


def window_report(f, seams=(), critic=None):
    """CE по всем окнам WIN + окну ±SEAM_HALF и RMS по сторонам каждого стыка. Сбой критика = исключение."""
    ws = windows(duration(f))
    with tempfile.TemporaryDirectory() as td:  # t_3c6b9f04: w/s000NN.wav (до 620 MB) удаляются и при сбое
        clips = [cut(f, s, l, f"{td}/w{i:05d}.wav") for i, (s, l) in enumerate(ws)]
        clips += [cut(f, t - SEAM_HALF, 2 * SEAM_HALF, f"{td}/s{i:05d}.wav") for i, t in enumerate(seams)]
        ce = _critic(clips, critic)
    return {"wins": [(s, round(c, 3)) for (s, _), c in zip(ws, ce)],
            "seams": [{"t": t, "ce": round(c, 3), "rms_l": round(rms_db(f, t - SEAM_HALF, min(SEAM_HALF, t)), 2),
                       "rms_r": round(rms_db(f, t, SEAM_HALF), 2)} for t, c in zip(seams, ce[len(ws):])]}


def full_ce_why(f, seams=(), critic=None):
    """R1-R3 по всему треку. R5: сбой критика не исключение, а причина FAIL (вслепую не публикуем)."""
    try:
        rep = window_report(f, list(seams), critic)
    except Exception as e:
        return [f"R5 сбой критика: {str(e)[:400]}"], {}
    return ce_why(rep["wins"]) + seam_why(rep["seams"]), rep


def ce_windows_batch(files, critic=None):
    """Гейт сегмента час-микса (gated_gen/best-of): CE КАЖДОГО окна WIN каждого файла одним прогоном критика.
    Возврат [[ce окна, ...], ...] в порядке files; min() = R1 сегмента. Ошибка критика = исключение."""
    clips, n, out = [], [], []
    with tempfile.TemporaryDirectory() as td:
        for fi, f in enumerate(files):
            ws = windows(duration(f))
            clips += [cut(f, s, l, f"{td}/f{fi:03d}w{i:04d}.wav") for i, (s, l) in enumerate(ws)]
            n.append(len(ws))
        ce = _critic(clips, critic)
    for k in n:
        out, ce = out + [ce[:k]], ce[k:]
    return out


def ce_scores(f):
    return ce_batch([f])[0]


def ce_batch(files, critic=None):
    """t_b4006a6e (best-of сегментов): CE 3 отрывков по 30 с (10/50/90 %) на трек одним прогоном критика.
    Возврат [[c,c,c], ...] в порядке files. Ошибка критика = исключение (FAIL)."""
    clips = []
    with tempfile.TemporaryDirectory() as td:
        for fi, f in enumerate(files):
            dur = duration(f)
            clips += [cut(f, dur * frac - 15, 30, f"{td}/t{fi:03d}c{i}.wav") for i, frac in enumerate((0.1, 0.5, 0.9))]
        ce = _critic(clips, critic)
    return [ce[3 * i:3 * i + 3] for i in range(len(files))]


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


# V9: обложка (кадр ролика и миниатюра) слишком тёмная/пересвеченная = не читается в ленте. YAVG по signalstats
# (limited range: чистый чёрный 16, чистый белый 235). Замер 21.10, 20 миниатюр канала: 28.9..66.3 (самая тёмная —
# «Rainy Night in Tokyo», ночные phonk 32-55) — все проходят; брак = почти чёрный кадр (сбой генерации) или засвет.
COVER_YMIN, COVER_YMAX = 24, 220


def cover_why(png):
    """V9: [причина], если средняя яркость обложки вне [COVER_YMIN, COVER_YMAX]. Нет файла = [] (это integrity)."""
    if not os.path.exists(str(png)):
        return []
    e = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(png), "-vf", "signalstats,metadata=print",
                        "-frames:v", "1", "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.findall(r"signalstats\.YAVG=([\d.]+)", e)
    if not m:
        return []
    y = float(m[-1])
    if y < COVER_YMIN:
        return [f"обложка тёмная: яркость {y:.0f} < {COVER_YMIN} из 255 (не читается в ленте)"]
    return [f"обложка пересвечена: яркость {y:.0f} > {COVER_YMAX} из 255"] if y > COVER_YMAX else []


def fallback_why(d):
    """V14: [причина], если 02_cover поставил градиент-заглушку (image API упал) — пустая картинка не публикуется."""
    f = os.path.join(str(d), "cover_fallback.json")
    if not os.path.exists(f):
        return []
    try:
        r = json.load(open(f, encoding="utf-8")).get("reason", "")
    except ValueError:
        r = "маркер повреждён"
    return [f"обложка-заглушка без арта (image API: {r[:120]})"]


# V3: шортс = вертикаль 9:16, <= 60 с, есть видео+звук; иначе YouTube не кладёт его в ленту Shorts.
SHORT_MAX, SHORT_AR, SHORT_AR_TOL = 60.0, 9 / 16, 0.01


def short_why(f):
    """V3: [причины], почему файл не годится как Shorts (формат/длительность/потоки)."""
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                                   "-of", "json", str(f)], capture_output=True, text=True).stdout or "{}")
    st = {s.get("codec_type"): s for s in j.get("streams", [])}
    if "video" not in st or "audio" not in st:
        return [f"шортс: нет потока {sorted(st)} (нужны video+audio)"]
    w, h = int(st["video"].get("width") or 0), int(st["video"].get("height") or 0)
    d = float(j.get("format", {}).get("duration") or 0)
    why = [] if h and abs(w / h - SHORT_AR) <= SHORT_AR_TOL else [f"шортс {w}x{h} не 9:16"]
    return why + ([f"шортс {d:.1f} с > {SHORT_MAX:.0f} с"] if d > SHORT_MAX else [])


# A24: шортс режется из середины трека; без фейдов старт/конец = щелчок в ленте Shorts. 07 накладывает SHORT_FADES,
# гейт проверяет края: первые/последние EDGE_WIN с тише всего шортса минимум на EDGE_DROP дБ.
SHORT_FADE_IN, SHORT_FADE_OUT = 0.5, 1.5
SHORT_FADES = "afade=t=in:d=0.5,afade=t=out:st={st:.2f}:d=1.5"
EDGE_WIN, EDGE_DROP = 0.05, 12.0


# V8: 720p в ленте выглядит дёшево и не получает HD-ранжирование (p-kkEmLGviU был 1280x720).
MIN_SHORT = 1080


def res_why(f):
    """V8: [причина], если короткая сторона видео < 1080 (720p = дёшево, HD-ранжирование ниже)."""
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height", "-of", "json", str(f)],
                                  capture_output=True, text=True).stdout or "{}")
    st = (j.get("streams") or [{}])[0]
    w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    if not w or not h:
        return []  # нет видео-потока — разрешение не наша проверка
    return [f"разрешение {w}x{h}: короткая сторона < {MIN_SHORT} (V8: 720p выглядит дёшево)"] \
        if min(w, h) < MIN_SHORT else []


def short_edge_why(f):
    """A24: [причины], если шортс начинается/кончается скачком (нет фейда)."""
    d = duration(f)
    whole = rms_db(f, 0, d)
    head, tail = rms_db(f, 0, EDGE_WIN) - whole, rms_db(f, d - EDGE_WIN, EDGE_WIN) - whole
    why = [f"шортс: резкое начало {head:+.1f} дБ к шортсу (нужно < -{EDGE_DROP})"] if head > -EDGE_DROP else []
    return why + ([f"шортс: резкий конец {tail:+.1f} дБ к шортсу (нужно < -{EDGE_DROP})"] if tail > -EDGE_DROP else [])


def end_why(f):
    """A16: [причина], если последние END_WIN с не тише всего трека на END_DROP дБ (обрыв без затухания)."""
    d = duration(f)
    whole, tail = rms_db(f, 0, d), rms_db(f, d - END_WIN, END_WIN)
    return [f"резкий конец: последние {END_WIN} с {tail:.1f} дБ при треке {whole:.1f} дБ "
            f"(затухание {tail - whole:+.1f} < {END_DROP} дБ)"] if tail - whole > -END_DROP else []


def stereo_why(f):
    """A9: [причина], если сведение в моно теряет > MONO_LOSS дБ (противофаза). Моно-файл совместим по определению."""
    ch = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
                         "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout.strip()
    if ch != "2":
        return []
    rms = lambda af: float((re.findall(r"RMS level dB: (-?[\d.]+|-inf)", ff(f, af + "astats=measure_overall=RMS_level:"
                           "measure_perchannel=none")) or ["-200"])[-1].replace("-inf", "-200"))
    loss = rms("") - rms("pan=mono|c0=0.5*c0+0.5*c1,")
    return [f"моно-совместимость: сведение в моно теряет {loss:.1f} дБ > {MONO_LOSS} (каналы в противофазе)"] if loss > MONO_LOSS else []


def sub_why(f):
    """A17: [причина], если энергия < 20 Гц (инфразвук/DC) громче SUB_MAX дБ относительно всего трека."""
    rms = lambda af: float((re.findall(r"RMS level dB: (-?[\d.]+|-inf)", ff(f, af + "astats=measure_overall=RMS_level:"
                           "measure_perchannel=none")) or ["-200"])[-1].replace("-inf", "-200"))
    sub = rms("lowpass=f=20,lowpass=f=20,") - rms("")
    return [f"инфразвук/DC: энергия < 20 Гц {sub:+.1f} дБ к треку > {SUB_MAX} (съедает громкость)"] if sub > SUB_MAX else []


def loudjump_why(f):
    """A18: [причина] на каждый скачок медианы short-term LUFS между соседними блоками JUMP_BLOCK с > JUMP_MAX."""
    st = [float(x) for x in re.findall(r"S:\s*(-?[\d.]+)", ff(f, "ebur128=framelog=info"))][:-1]  # шаг 0.1 с
    st, n = st[30:max(30, len(st) - int(TAIL * 10))], int(JUMP_BLOCK * 10)
    med = lambda a: sorted(a)[len(a) // 2]
    blk = [med(st[i:i + n]) for i in range(0, len(st) - n + 1, n)]
    return [f"скачок громкости {abs(b - a):.1f} LU между блоками {i * JUMP_BLOCK + 3:.0f} и {(i + 1) * JUMP_BLOCK + 3:.0f} с "
            f"(> {JUMP_MAX})" for i, (a, b) in enumerate(zip(blk, blk[1:])) if abs(b - a) > JUMP_MAX]


def tunings(f, sr=11025, n=8192):
    """A19: строй (центы от A440, -50..50) по окнам TUNE_WIN с; окна без согласованных тональных пиков пропускаются."""
    import numpy as np
    x = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                                     capture_output=True).stdout, np.float32)
    fq, win, out = np.fft.rfftfreq(n, 1 / sr), int(TUNE_WIN * sr), []
    for i in range(0, len(x) - win // 2, win):
        seg = x[i:i + win]
        fr = np.array([seg[j:j + n] * np.hanning(n) for j in range(0, len(seg) - n, n)])
        if not len(fr):
            continue
        S = np.abs(np.fft.rfft(fr, axis=1))
        S[:, (fq < 100) | (fq > 2000)] = 0
        z, w = 0j, 0.0
        for s in S:
            k = np.where((s[1:-1] > s[:-2]) & (s[1:-1] > s[2:]) & (s[1:-1] > s.max() * 0.1))[0] + 1
            if s.max() <= 0 or not len(k):
                continue
            a, b, c = s[k - 1], s[k], s[k + 1]
            hz = (k + 0.5 * (a - c) / np.where(a - 2 * b + c == 0, -1e-12, a - 2 * b + c)) * sr / n
            z += np.sum(b * np.exp(2j * np.pi * 12 * np.log2(hz / 440.0)))
            w += float(b.sum())
        if w > 0 and abs(z) / w >= TUNE_MIN_R:  # иначе строя в окне нет — угол случайный
            out.append(float(np.angle(z) * 50 / np.pi))
    return out


def tuning_why(f):
    """A19: [причина], если строй между окнами расходится больше TUNE_MAX центов (круговой разброс)."""
    import cmath
    t = tunings(f)
    if len(t) < 2:
        return []
    m = cmath.phase(sum(cmath.exp(2j * cmath.pi * v / 100) for v in t)) * 50 / cmath.pi
    dev = [(v - m + 50) % 100 - 50 for v in t]
    spread = max(dev) - min(dev)
    return [f"строй плывёт: разброс {spread:.0f} центов между окнами {TUNE_WIN:.0f} с > {TUNE_MAX:.0f} "
            f"(окно {dev.index(max(dev)) * TUNE_WIN:.0f} с против {dev.index(min(dev)) * TUNE_WIN:.0f} с)"] if spread > TUNE_MAX else []



# A27: YouTube перекодирует звук в Opus и поднимает true peak речи. Замер 26.10 YouTube-копий канала 2:
# K5cqI_AX4hk TP -0.3, kQauDNrBAWU -0.8 dBTP (мастер проходил MAX_TP -1.0); A26: Opus +0.6 дБ.
# Мастер речи обязан иметь запас: TP <= MAX_TP - OPUS_OVERSHOOT (-1.6). Мастер A26 (loudnorm TP=-2.0) проходит.
OPUS_OVERSHOOT = 0.6
SPEECH_TP_MAX = MAX_TP - OPUS_OVERSHOOT


def speech_why(f):
    """A25: звук речевого ролика (edge-tts): громкость MIN_I..MAX_I, true peak <= MAX_TP, нет тишины >= SIL_MIN с
    ниже SIL_DB (сбой TTS пункта = пустой mp3) вне первых 0.5 с и последней 1 с. Замер 23.10 канала 2 с YouTube
    (7 роликов): I -14.5..-13.9, TP -1.5..-1.0, макс. пауза между фразами 1.52 с."""
    e = ff(f, f"ebur128=peak=true,silencedetect=n={SIL_DB}dB:d={SIL_MIN}")
    if "Peak:" not in e:
        return ["нет звука"]
    li = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", e)[-1])
    tp = float(re.findall(r"Peak:\s+(-?[\d.]+|-inf)", e)[-1].replace("-inf", "-200"))
    dur = duration(f)
    st = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", e)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", e)] + [dur] * len(st)
    why = loud_why(li) + ([f"true peak {tp:+.1f} dBTP > {SPEECH_TP_MAX}: клиппинг после Opus YouTube"]
                          if tp > SPEECH_TP_MAX else [])
    return why + [f"тишина {b - a:.1f} с на {a:.1f} с (< {SIL_DB} дБ): сбой озвучки" for a, b in zip(st, en)
                  if a > 0.5 and b < dur - 1.0]


def video_why(d):
    """P19: гейт речевых видео-форматов (listshow/whatif: render.json long+shorts; owning: video.mp4 = Short) до заливки.
    Целостность/синхрон (V2/V3), чёрный кадр (V1), формат шортса (V3), обложка (V9). Музыкальные эталоны тут не применимы."""
    d = str(d)
    rj = os.path.join(d, "render.json")
    if os.path.exists(rj):
        meta = json.load(open(rj, encoding="utf-8"))
        longs, shorts = [x for x in [meta.get("long")] if x], list(meta.get("shorts") or [])
    else:
        longs, shorts = [], [os.path.join(d, "video.mp4")]
    why = []
    for f in longs + shorts:
        if not os.path.exists(str(f)):
            why.append(f"нет файла {os.path.basename(str(f))}")
            continue
        tag = os.path.basename(str(f))
        why += [f"{tag}: {w}" for w in integrity_why(f) + black_why(f) + res_why(f) + speech_why(f) + (short_why(f) if f in shorts else [])]
    return why + cover_why(os.path.join(d, "cover.png"))


def target(d, final):
    """--final: финальный файл после 04 assemble (то, что заливается), иначе трек после 03."""
    return d / ("video.mp4" if final else "track.mp3")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if "--video" in argv:  # P19: речевые форматы (listshow/whatif/owning) — тот же стоп до заливки
        from common import latest_run_dir
        why = video_why(args[0] if args else latest_run_dir())
        for w in why:
            print(f"::error::quality gate: {w}")
        return 1 if why else 0
    expect, seams = None, []
    if args:
        f, genre = args[0], args[1]
    else:
        from common import latest_run_dir
        d = latest_run_dir()
        meta = json.loads((d / "music_meta.json").read_text(encoding="utf-8"))
        f, genre, seams = target(d, "--final" in argv), meta["genre"], meta.get("seams") or []
        if (d / "track.mp3").exists():
            expect = streams(d / "track.mp3")["format"]
    for a in argv:
        if a.startswith("--seams="):
            seams = [float(x) for x in a[8:].split(",") if x]
    why, m = objective(f, genre)
    why += stereo_why(f)  # A9
    why += sub_why(f)  # A17
    why += loudjump_why(f)  # A18
    why += tuning_why(f)  # A19
    why += end_why(f)  # A16: только целый трек/финальный mp4, не сегменты best-of (их хвосты режет склейка)
    if "--final" in argv:
        why += integrity_why(f, expect) + black_why(f) + res_why(f)
        why += cover_why(os.path.join(os.path.dirname(str(f)), "cover.png"))  # V9
        why += fallback_why(os.path.dirname(str(f)))  # V14
        cs = os.path.join(os.path.dirname(str(f)), "cover_source.json")  # t_629a7ba2: какой путь дал обложку
        if os.path.exists(cs):
            src = json.load(open(cs, encoding="utf-8"))
            print(f"cover_source: {src.get('path')} {src.get('model') or src.get('file') or ''}".rstrip())
    if "--no-ce" not in argv:  # R4: окна CE/дрейф/стыки и на финальном mp4 (04b) — мерим то, что заливается
        w, rep = full_ce_why(f, seams)
        why += w
        if rep:
            ce = [c for _, c in rep["wins"]]
            m.update(ce_min=min(ce), ce_windows=rep["wins"], seams=rep["seams"])
    print(json.dumps({"track": str(f), "genre": genre, **m, "fail": why}, ensure_ascii=False))
    for w in why:
        print(f"::error::quality gate: {w}")
    return 1 if why else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
