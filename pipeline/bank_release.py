#!/usr/bin/env python3
"""t_ba72c7aa R2: выпуск собирается из банка одобренных сегментов, генерации в слоте нет.

Банк = /app/output/bank/<жанр> в контейнере ace-step (bind C:/dockerlocal/ace15/output).
Сегменты совместимы по (BPM, тональность) промпта; анти-повтор 14 дней (использованный
сегмент не попадает в следующий выпуск), файлы использованных удаляются из банка через 30 дней.
Сборка = prep_segments + concat_tracks из 03_music (тот же путь, что у час-микса),
music_meta.json с chapters/seams — критики 03c/04b меряют то же, что и раньше.
Пустой банк / нет совместимой группы = exit 2 (слот пропускается, шаги гейтятся nobank) —
брак не публикуется.
"""
import importlib.util
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
BANK_ROOT = "/app/output/bank"
USED_BLOCK_DAYS = 14   # сегмент не попадает во второй выпуск 14 дней
RETAIN_USED_DAYS = 30  # использованный сегмент удаляется из банка через 30 дней
COMPAT_BPM = 4         # добор из соседних групп: BPM в пределах +-4 (коммент 24.10 «±4 BPM»)
LOFI_MAX_BPM = 75     # 25.10 владелец: 89 BPM «слишком энергично» для lofi, цель 64-72
MIN_SEG = 5            # короткий микс вместо пропуска слота: 5 x 180 с = 15 мин (прошлый минимум)
ROOT = HERE.parent

# Замеры сборки (консервативно): cp сегмента ~1 c, prep (edge_match/ffmpeg) ~5 c,
# concat через acrossfade ~15 c на сегмент, критик 03c по окнам ~120 c плоско.
CP_SEC, PREP_SEC, CONCAT_SEC, CRITIC_SEC = 1, 5, 15, 120


def slug(genre: str) -> str:
    return genre.replace(" ", "-")


def bank_dir(genre: str) -> str:
    return f"{BANK_ROOT}/{slug(genre)}"


def release_budget_sec(n_seg: int) -> int:
    """Оценка времени выпуска из n_seg сегментов: < 900 = слот успевает (критерий 5)."""
    return CP_SEC * n_seg + PREP_SEC * n_seg + CONCAT_SEC * n_seg + CRITIC_SEC


def _music():
    spec = importlib.util.spec_from_file_location("acf_music03f", HERE / "03_music.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["acf_music03f"] = m
    spec.loader.exec_module(m)
    return m


def group_key(entry: dict) -> tuple:
    """Совместимость перехода = (bpm, тональность) из текста промпта (03_music.prompt_*)."""
    m = _music()
    p = entry.get("prompt") or ""
    return (m.prompt_bpm(p), m.prompt_key(p))


def entries(genre: str, docker_sh=None) -> list[dict]:
    """Список сегментов банка с мета; *.mp3 без валидного json молча пропускаются."""
    d = bank_dir(genre)
    listing = docker_sh("exec", "ace-step", "sh", "-c", f"ls {d} 2>/dev/null")
    out = []
    for line in listing.splitlines():
        name = line.strip()
        if not name.endswith(".mp3"):
            continue
        try:
            meta = json.loads(docker_sh("exec", "ace-step", "sh", "-c", f"cat {d}/{name[:-4]}.json"))
            assert isinstance(meta, dict)
        except Exception:
            continue
        out.append({"name": name[:-4], **meta})
    return out


def _used_filter(used_lines, now):
    """Имена, использованные за последние USED_BLOCK_DAYS; битые строки молча пропускаются."""
    used = set()
    for x in used_lines or []:
        try:
            row = json.loads(x)
            if now - float(row["ts"]) < USED_BLOCK_DAYS * 86400:
                used.add(row["name"])
        except Exception:
            continue
    return used


def _keys_related(k1: tuple, k2: tuple) -> bool:
    """Соседние группы совместимы для кроссфейда: BPM в пределах COMPAT_BPM И тональность
    та же или та же тоника (F major / F minor — родственные, лад сгладит кроссфейд).
    None в ключе (группа без разметки) совместима только сама с собой."""
    if k1 == k2:
        return True
    (b1, t1), (b2, t2) = k1, k2
    if b1 is None or b2 is None or t1 is None or t2 is None:
        return False
    if abs(b1 - b2) > COMPAT_BPM:
        return False
    return t1.split()[0] == t2.split()[0]


def energy_ok(entries_: list[dict], genre: str) -> list[dict]:
    """Lofi: только сегменты с темпом <= LOFI_MAX_BPM (темп = поле bpm генерации из текста
    промпта, иначе meta bpm). Нет темпа = не берём: проверить нельзя. Другие жанры как есть."""
    if "lofi" not in genre:
        return entries_
    m = _music()
    out = []
    for e in entries_:
        b = m.prompt_bpm(e.get("prompt") or "") or e.get("bpm")
        if b and int(b) <= LOFI_MAX_BPM:
            out.append(e)
    return out


def pick(entries_: list[dict], need: int, now: float, used_lines=None, rng=None) -> list[dict] | None:
    """Совместимая группа: наибольшая по (bpm, key); < need = добор из совместимых групп
    (то же/родственная тональность, BPM +-COMPAT_BPM, коммент 24.10); и это не набирает
    need = короткий микс >= MIN_SEG вместо пропуска слота; < MIN_SEG = None."""
    used = _used_filter(used_lines, now)
    cands = [e for e in entries_ if e["name"] not in used]
    groups: dict[tuple, list[dict]] = {}
    for e in cands:
        groups.setdefault(group_key(e), []).append(e)
    if not groups:
        return None
    rng = rng or random.Random()
    best = max(groups.values(), key=len)
    rng.shuffle(best)
    if len(best) >= need:
        return best[:need]
    core = list(best)
    k0 = group_key(best[0])
    for k in sorted(groups, key=lambda k: -len(groups[k])):
        if k == k0 or not _keys_related(k0, k):
            continue
        for e in groups[k]:
            if len(core) >= need:
                break
            core.append(e)
    if len(core) >= need:
        rng.shuffle(core)
        return core[:need]
    if len(core) >= MIN_SEG:
        return core
    return None



def _ffprobe_detail(path) -> str:
    """Диагностика: почему ffprobe счёл сегмент нечитаемым (слоты 18:28/21:00/23:10
    исключали сегменты с сошедшимся размером — причина класса не зафиксирована)."""
    import subprocess
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
        return f"rc={r.returncode} out={r.stdout.strip()[:80]!r} err={r.stderr.strip()[:160]!r}"
    except Exception as e:
        return f"{type(e).__name__}: {e}"

def _valid_audio(path) -> bool:
    """Скопированный сегмент читается ffprobe и длится > 1 с (битый/недописанный mp3 = False)."""
    import subprocess
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and float(r.stdout.strip() or 0) > 1.0
    except Exception:
        return False


MAX_SWING_DB = 8.0  # run 40155188504: сегмент с внутренним провалом 4.7 LU (1143-1203с) валит loudjump гейта трека


SWING_EDGE, SWING_AVG = 20, 10  # с: края-фейды не судим (= trim_fade max_sec); окно усреднения


def internal_swing(path):
    """(min,max) RMS дБ по 1с-окнам - глубина внутренних провалов громкости.
    asetnsamples режет поток на окна по 1 с (44100 сэмплов), astats reset=1 = RMS каждого окна.
    25.10: ebur128-вариант (df3b0ab) парсил stdout при -loglevel error, а ebur128 пишет в stderr ->
    всегда (-120,-120), детектор провалов был выключен, CI master красный."""
    import re
    import subprocess
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-i", str(path), "-af",
                           "aresample=44100,asetnsamples=n=44100:p=0,"
                           "astats=metadata=1:reset=1:measure_overall=RMS_level:measure_perchannel=none,"
                           "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                           "-f", "null", "-"], capture_output=True, text=True)
    win = [float(x) if x != "-inf" else -120.0
           for x in re.findall(r"RMS_level=(-?[\d.]+|-inf)", proc.stdout)]
    # 26.10: min/max сырых 1с-окон ловил штатные fade-in/out краёв (до -76 дБ) => провал 52-69 дБ
    # у КАЖДОГО сегмента, весь банк в карантине (run 40243598650). Края <= SWING_EDGE с не судим
    # (их и так режут trim_fade_head/tails и acrossfade), окна усредняем по энергии за SWING_AVG с
    # (как блоки A18 гейта, а не одиночная тихая доля).
    import math
    win = win[SWING_EDGE:len(win) - SWING_EDGE]
    if len(win) < SWING_AVG:
        return (-120.0, -120.0)
    lin = [10 ** (x / 10) for x in win]
    avg = [10 * math.log10(sum(lin[i:i + SWING_AVG]) / SWING_AVG + 1e-12) for i in range(len(lin) - SWING_AVG + 1)]
    return (min(avg), max(avg))


def take(genre: str, need: int, run_dir: str, docker_sh=None, now=None, rng=None,
         valid=None) -> list[Path] | None:
    """Выбрать и скопировать need сегментов в run_dir. None = банк/совместимость недостатны.
    Битый сегмент (cp не удался / mp3 недописан, run 39848167892) исключается и добирается
    другим; битых не хватает на замену = None (слот пропускается, не падает)."""
    valid = valid or _valid_audio
    d = bank_dir(genre)
    ents = energy_ok(entries(genre, docker_sh=docker_sh), genre)
    used_path = ROOT / ".state/bank_used.jsonl"
    used_lines = []
    try:
        used_lines = used_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        pass
    t = now if now is not None else time.time()
    bad: set[str] = set()
    good: dict[str, Path] = {}
    while True:
        got = pick([e for e in ents if e["name"] not in bad], need, t, used_lines, rng)
        if got is None:
            if bad:
                print(f"::warning::банк {genre}: битые сегменты исключены: {sorted(bad)}")
            return None
        out = []
        for e in got:
            n = e["name"]
            if n not in good:
                dst = Path(run_dir) / f"{n}.mp3"
                dst.parent.mkdir(parents=True, exist_ok=True)  # ACF_RUN_DIR нет после clean-checkout: docker cp rc=1 -> «не доставлен» -> nobank
                # ПРОВЕРКА ОДНА - при записи в банк (put_verified sha256). Здесь только
                # доставка: cp не удался физически = повтор, 5 попыток. Судить файл "битым"
                # выпуск не имеет права - это вторая проверка того же файла (24.10: выпуск
                # карантинил 15 целых сегментов, проверка врала на отсутствии tmp-папки).
                ok = False
                for _attempt in range(1, 6):
                    r = docker_sh("cp", f"ace-step:{d}/{n}.mp3", str(dst))
                    if dst.exists() and dst.stat().st_size > 0 and "invalid output path" not in str(r):
                        ok = True
                        break
                    time.sleep(2)
                if not ok:
                    bad.add(n)
                    print(f"::warning::банк {genre}: доставка {n} не удалась (5 попыток cp)")
                    break
                lo, hi = internal_swing(dst)
                if hi - lo > MAX_SWING_DB:
                    bad.add(n)
                    good.pop(n, None)
                    dst.unlink(missing_ok=True)
                    print(f"::warning::банк {genre}: {n} исключён (внутренний провал {hi - lo:.1f} дБ > {MAX_SWING_DB})")
                    break
                good[n] = dst
            out.append(good[n])
        else:
            for n, pth in list(good.items()):
                if pth not in out:
                    pth.unlink(missing_ok=True)
            return out


def used_record(names: list[str], now: float, state_path: Path | None = None) -> None:
    """Пометить использованные сегменты (jsonl)."""
    state_path = Path(state_path or ROOT / ".state/bank_used.jsonl")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("a", encoding="utf-8") as f:
        for n in names:
            f.write(json.dumps({"name": n, "ts": now}, ensure_ascii=False) + "\n")


def used_cleanup(now: float, state_path: Path | None = None, docker_sh=None) -> int:
    """Удалить из стейта и банка сегменты, использованные раньше RETAIN_USED_DAYS."""
    state_path = Path(state_path or ROOT / ".state/bank_used.jsonl")
    try:
        rows = [json.loads(x) for x in state_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return 0
    keep, removed = [], 0
    d = None
    for row in rows:
        try:
            if now - float(row["ts"]) < RETAIN_USED_DAYS * 86400:
                keep.append(row)
                continue
        except Exception:
            keep.append(row)
            continue
        removed += 1
        d = d or bank_dir("anime lofi")
        n = row["name"]
        docker_sh("exec", "ace-step", "sh", "-c", f"rm -f {d}/{n}.mp3 {d}/{n}.json")
    if removed:
        state_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep), encoding="utf-8")
    return removed


def _music_mod():
    """03_music одним экземпляром: тесты патчат sys.modules["acf_music03"]."""
    if "acf_music03" in sys.modules:
        return sys.modules["acf_music03"]
    spec = importlib.util.spec_from_file_location("acf_music03", HERE / "03_music.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["acf_music03"] = m
    spec.loader.exec_module(m)
    return m


LIMIT_DB = -6.0  # t_96de1cc6: потолок alimiter; гейт MAX_TP -3.0, 3 дБ запаса на mp3-овершут
TP_SAFE = -3.5   # после кодирования TP выше -> статический доворот вниз (гейт -3.0 не трогаем)
LN_PASSES = 8    # t_2c32a785/t_32ee66e0: рендеров с доводкой остатка громкости после лимитера
LN_TOL = 0.5     # допуск к LUFS_TARGET (гейт MIN_I..MAX_I = цель -2/+1)


def _next_gain(pts: list, target: float) -> float:
    """t_32ee66e0 (run 40527578183: phonk -16.2 LUFS после фикса t_2c32a785): под лимитером I(gain)
    немонотонна — громкость пикового трека сидит в пиках, лимитер их срезает всё агрессивнее с
    ростом gain (замер: +12 дБ -> -15.9, +14 дБ -> -19.5 LUFS). Шаг gain += target - I в такой яме
    уходит назад или топчется, фиксированного числа рендеров не хватает (выпуски -16.1..-16.5).
    Бисекция по вилке (gain тише цели, gain громче цели); без вилки — шаг минимум 3 дБ в сторону
    цели, чтобы выйти из плоского участка быстрее одного дБ за рендер."""
    lo = [p for p in pts if p[1] < target]
    hi = [p for p in pts if p[1] >= target]
    # без вилки шаг удваивается (3, 6, 12, 24 дБ): на «стене» I ползёт ~0.3 LU/3 дБ, линейный шаг
    # не доходил до вилки за LN_PASSES (замер t_32ee66e0: 8 рендеров, лучший -16.1..-16.4)
    step = 3.0 * 2 ** min(len(pts) - 1, 3)
    if not hi:
        g, i = max(lo, key=lambda p: p[0])
        return g + max(target - i, step)
    if not lo:
        g, i = min(hi, key=lambda p: p[0])
        return g - max(i - target, step)
    g_hi, i_hi = min(hi, key=lambda p: p[0])
    below = [p for p in lo if p[0] < g_hi]
    if not below:
        return g_hi - max(i_hi - target, 3.0)
    g_lo = max(below, key=lambda p: p[0])[0]
    return (g_lo + g_hi) / 2


def loudnorm_2pass(src: str, dst: str) -> dict:
    """Двухпроходная нормализация: 1-й проход меряет I (ebur128), 2-й = постоянный gain к LUFS_TARGET
    (динамики нет, LRA не давится) + alimiter LIMIT_DB на 4x частоте.
    t_2c32a785: раньше 2-й проход = loudnorm linear=true. ffmpeg держит linear только если
    measured_TP + gain <= TP цели; на пиковом lofi/phonk (бочка) это не так, и loudnorm молча уходит
    в динамический режим, который недотягивает: выпуски -16.1..-16.5 LUFS при гейте -16..-13.
    Лимитер срезает пики вместе с частью громкости, поэтому остаток до цели меряем и довешиваем к gain."""
    import re as _re
    import subprocess
    import mastering
    from quality_gate import LUFS_TARGET
    # 1-й проход = ebur128 вместо loudnorm-анализа: на часе 20 с против 127 с (run 40253826993).
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-map", "0:a", "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True, check=True).stderr
    tail = err[err.rindex("Summary:"):]
    num = lambda k: _re.search(k + r":\s+(-?[\d.]+)", tail).group(1)
    j = {"input_i": num("I"), "input_thresh": num("Threshold"), "input_lra": num("LRA"), "input_tp": num("Peak")}
    # лимитер на 4x частоте: на 48 кГц он ловит сэмплы, не межсэмпловые пики (замер на банке: TP -0.7 vs -1.0)
    lim = f"aresample=192000,alimiter=limit={10 ** (LIMIT_DB / 20):.4f}:level=disabled:attack=1:release=50"
    tmp = dst + ".ln2.mp3"
    best = dst + ".ln2best.mp3"
    trim = dst + ".ln2tp.mp3"  # t_32ee66e0 review: доворот пишется сюда, НЕ в best (там лучший кандидат)
    # t_32ee66e0 (run 40612738736: шаг 03 timeout 20 мин): рендер часа ~35 c, замер ~20 c (ПК-раннер).
    # Доворот TP внутри каждого прохода = до 2 рендеров + 3 замера на проход, x8 проходов = ~30 мин.
    # Бюджет: 1 рендер + 1 замер на проход. Статический volume сдвигает I ровно на свои дБ, поэтому
    # I после доворота считаем без рендера (eff), рендерим доворот один раз — для лучшего кандидата.
    pts = []  # (gain, eff_I): I, которое уедет в dst после TP-доворота
    best_m = None
    gain = LUFS_TARGET - float(j["input_i"])
    for n in range(LN_PASSES):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af",
                        f"volume={gain:.2f}dB,{lim},aresample=48000", "-ar", "48000",
                        "-c:a", "libmp3lame", "-b:a", "192k", tmp], check=True)
        m = mastering.measure(tmp)
        i = m["i"] + min(0.0, TP_SAFE - m["tp"] - 0.1)
        print(f"loudnorm_2pass #{n + 1}: gain {gain:+.2f} dB -> I {m['i']} TP {m['tp']} (после доворота I {i:.2f})", flush=True)
        if not pts or abs(i - LUFS_TARGET) < abs(min(pts, key=lambda p: abs(p[1] - LUFS_TARGET))[1] - LUFS_TARGET):
            os.replace(tmp, best)
            best_m = m
        pts.append((gain, i))
        if abs(i - LUFS_TARGET) <= LN_TOL:
            break
        gain = _next_gain(pts, LUFS_TARGET)
    g, i = min(pts, key=lambda p: abs(p[1] - LUFS_TARGET))  # лучший рендер, не последний
    tp = best_m["tp"]
    for _ in range(2):  # mp3-кодер даёт овершут ~0.3-0.5 дБ: доворот вниз только у выбранного кандидата
        if tp <= TP_SAFE:
            break
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", best, "-af",
                        f"volume={TP_SAFE - tp - 0.1:.2f}dB", "-c:a", "libmp3lame", "-b:a", "192k", trim],
                       check=True)
        os.replace(trim, best)
        mm = mastering.measure(best)
        tp, i = mm["tp"], mm["i"]
    j["gain"], j["i"] = f"{g:.2f}", i
    if abs(i - LUFS_TARGET) > LN_TOL:
        print(f"::warning::loudnorm_2pass: не сошлось за {LN_PASSES} рендеров, лучший I {i} (цель {LUFS_TARGET:g}): {pts}")
    os.replace(best, dst)
    if os.path.exists(tmp):
        os.remove(tmp)
    return j


def master_final(track: str, genre: str) -> None:
    """t_96de1cc6: финальный мастер склейки = flatten_blocks (относительные gain блоков A18) ->
    fade_end -> loudnorm_2pass (постоянный gain к LUFS_TARGET + alimiter -1.5 дБ). Порядок: лимитер
    последним, flatten/fade до него (раньше flatten шёл после loudnorm и поднимал пики)."""
    m = _music_mod()
    flatten_blocks(track)
    m.fade_end(track)  # до лимитера: linear loudnorm хвост не подтягивает, а лишнее mp3-кодирование после — овершут
    loudnorm_2pass(track, track)


def _norm_segments(paths: list[Path], log=print) -> None:
    """Привести сегменты к LUFS_TARGET ДО склейки статическим gain + мягкий alimiter (-1.8 dBFS).
    t_5dbfa67a: раньше single-pass loudnorm (динамический режим) давил LRA каждого сегмента
    (фикстура 12.4 -> 6.9, run 40449097418: трек LRA 3.1 < 3.5 при CE 7.2) — тот же класс, что
    t_522ca872 в mastering.master. Внутренние LU-скачки (run 40155188504) выравнивает flatten_blocks
    по сетке гейта A18 на готовой склейке, сегментный компрессор для этого не нужен.
    t_9944c9ce: мягкий лимитер (LOFI_LIM_GENTLE) сохраняет LRA сегментов; TP-доворот делает master_final.
    """
    import mastering
    from quality_gate import LUFS_TARGET
    lim = mastering.LOFI_LIM_GENTLE  # -1.8 dBFS, сохраняет LRA
    def one(p):
        tmp = str(p) + ".ln.mp3"
        try:
            gain = LUFS_TARGET - mastering.measure(str(p))["i"]
        except Exception as e:  # noqa: BLE001 — битый замер не портит сегмент
            log(f"::warning::замер {p.name} не удался, сегмент как есть: {e}")
            return
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p),
                            "-af", f"volume={gain:.2f}dB,{lim}",
                            "-c:a", "libmp3lame", "-b:a", "192k", tmp],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.getsize(tmp) > 0:
            os.replace(tmp, p)
        else:
            log(f"::warning::нормализация {p.name} не удалась, сегмент как есть: {(r.stderr or '').strip()[:160]}")
    _music_mod().pmap(one, paths)



def flatten_blocks(track: str, log=print) -> None:
    """A18-гейт меряет медианы short-term LUFS 60-с блоков (JUMP_MAX=4.0). Интегрированная
    нормализация сегментов не выравнивает музыкальный контраст внутри сегмента: run 40171388541
    дал скачок 4.1 LU между блоками 1623/1683 с уже после per-segment loudnorm.
    Выравнивание по гейту: один проход ebur128 собирает медианы блоков, volume-автоматизация
    прижимает каждый блок к медиане трека (цель: дельта <= 2.5 LU < 4.0). Два прохода ffmpeg
    по готовому файлу, минуты на час — в P18-бюджете."""
    import re as _re
    import subprocess
    from quality_gate import JUMP_BLOCK, JUMP_MAX
    JB10 = int(JUMP_BLOCK * 10)  # JUMP_BLOCK float в quality_gate (60.0)
    # t_a771ef4f: допуск = половина цели. Блоки +2.4/-2.4 от медианы (каждый «в норме» при допуске 2.5)
    # дают соседям 4.8 LU > JUMP_MAX. При |g| <= tol для всех оставленных блоков сосед <= 2*tol < JUMP_MAX.
    tol = (JUMP_MAX - 1.5) / 2
    off = 30  # сетка блоков = сетка гейта (loudjump_why пропускает первые 3 с)
    r = subprocess.run(["ffmpeg", "-nostats", "-i", track,
                        "-af", "ebur128=framelog=info", "-f", "null", "-"],
                       capture_output=True, text=True)
    st = [float(x) for x in _re.findall(r"S:\s*(-?[\d.]+)", r.stderr)][:-1]  # шаг 0.1 с
    st = st[off:]
    nblk = len(st) // JB10
    if nblk < 2:
        log("::warning::flatten_blocks: мало отсчётов ebur128, пропуск")
        return
    meds = []
    for b in range(nblk):
        ch = sorted(st[b * JB10:(b + 1) * JB10])
        meds.append(ch[len(ch) // 2])
    whole = sorted(st)[len(st) // 2]
    # t_6633f8cd: исправляем только превышение допуска, не сводим музыку к
    # одной медиане. При коррекции <= 6 дБ блоки остаются в ±tol; предел 6 дБ не меняем.
    gains = [max(-6.0, min(6.0, whole - m - max(-tol, min(tol, whole - m)))) for m in meds]
    if not any(gains):
        return
    # последний блок тянется до конца файла: хвост < 60 с иначе остаётся без поправки
    end = lambda i: (i + 1) * JB10 / 10 + off / 10 if i < nblk - 1 else 1e9
    expr = "+".join(
        f"({10 ** (g / 20):.4f}-1)*between(t,{(i * JB10 + (off if i else 0)) / 10:.1f},{end(i):.1f})"
        for i, g in enumerate(gains) if g)
    af = f"volume=volume='1.0+{expr}':eval=frame"
    tmp = track + ".fl.mp3"
    rr = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", track,
                         "-af", af, "-c:a", "libmp3lame", "-b:a", "192k", tmp],
                        capture_output=True, text=True)
    if rr.returncode == 0 and os.path.getsize(tmp) > 0:
        os.replace(tmp, track)
    else:
        log(f"::warning::flatten_blocks не удался, трек как есть: {(rr.stderr or '').strip()[:160]}")


def assemble(paths: list[Path], run_dir: Path, metas: list[dict], genre: str, out: str = "track.mp3") -> dict:
    """Склейка сегментов банка тем же кодом, что час-микс (prep_segments + concat_tracks)."""
    m = _music_mod()

    seg = [{"name": e.get("name"), "seed": e.get("seed"), "prompt": e.get("prompt")} for e in metas]
    prompts = " | ".join(dict.fromkeys(str(e.get("prompt")) for e in metas))
    seed = int(metas[0].get("seed") or 0) if metas else 0

    _norm_segments(paths, log=print)
    m.prep_segments([str(p) for p in paths], log=print)
    import importlib.util
    if importlib.util.find_spec("librosa") is None:  # без сетки dj_plan молча откатился бы на xfade
        raise RuntimeError("librosa не установлен: DJ-стык по битам невозможен (t_96de1cc6)")
    starts, seams = m.concat_tracks([str(p) for p in paths], str(Path(run_dir) / out))
    master_final(str(Path(run_dir) / out), genre)
    chapters = m.chapters_at(starts, m.track_names(len(paths), seed))
    duration = int(m._probe_sec(Path(run_dir) / out))
    meta = {"genre": genre, "prompt": prompts, "seed": seed, "duration": duration,
            "segments": seg, "chapters": chapters, "seams": seams, "bank": True}
    (Path(run_dir) / "music_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def disk_gate_rc(need_gb: int = 1) -> int:
    """t_1f53095a R3: единый пол C: (deploy/gpu-pc/disk_gate.sh c) — и для fill, и для take.
    ponytail: любой rc != 0 (в т.ч. сбой самого гейта) = пропуск слота; fail-closed, алерт nobank виден."""
    gate = ROOT / "deploy/gpu-pc/disk_gate.sh"
    return subprocess.run(["sh", str(gate), "c", str(need_gb)]).returncode


def main(argv=None) -> int:
    argv = list(argv or [])
    genre = os.environ.get("GENRE", "anime lofi")
    duration = int(os.environ.get("TRACK_DURATION_SEC", "3600"))
    n_seg = -(-duration // 180)  # банк = 180-с сегменты: час = 20 шт
    run_dir = Path(os.environ.get("ACF_RUN_DIR") or (ROOT / "runs"))

    def sh(*a):
        import subprocess
        r = subprocess.run(["docker", *a], capture_output=True, text=True)
        if r.returncode != 0:  # cp-ошибки были невидимы: тихий None -> «битые» без единой строки лога (t_ba72c7aa)
            print(f"docker {' '.join(a[:2])}: rc={r.returncode}: {(r.stderr or r.stdout).strip()[:200]}")
        return r.stdout

    if disk_gate_rc() != 0:
        print(f"::warning::nobank: банк {genre}: на C: ниже пола disk_floors.env — слот пропущен, выпуск не собираем")
        return 2
    paths = take(genre, n_seg, str(run_dir), docker_sh=sh)
    if paths is None:
        reason = (f"банк {genre}: нет {n_seg} совместимых свободных сегментов — слот пропущен, "
                  "брак не публикуем (t_ba72c7aa)")
        print(f"::warning::{reason}")
        if "reason=" not in " ".join(argv):
            print(f"nobank: {reason}")
        return 2
    metas = entries(genre, docker_sh=sh)
    by_name = {e["name"]: e for e in metas}
    ordered = [by_name[p.stem] for p in paths]
    assemble(paths, run_dir, ordered, genre)
    used_record([p.stem for p in paths], time.time())
    used_cleanup(time.time(), docker_sh=sh)
    print(f"track -> {run_dir / 'track.mp3'} (bank, {len(paths)} сегментов)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
