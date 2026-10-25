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


def take(genre: str, need: int, run_dir: str, docker_sh=None, now=None, rng=None,
         valid=None) -> list[Path] | None:
    """Выбрать и скопировать need сегментов в run_dir. None = банк/совместимость недостатны.
    Битый сегмент (cp не удался / mp3 недописан, run 39848167892) исключается и добирается
    другим; битых не хватает на замену = None (слот пропускается, не падает)."""
    valid = valid or _valid_audio
    d = bank_dir(genre)
    ents = entries(genre, docker_sh=docker_sh)
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


def master_final(track: str, genre: str) -> None:
    """t_cron1024b (run 40087548227): сегменты мастерились поодиночке, но concat перекодирует
    и поднимает пики — TP склейки -0.8 dBTP > порога гейта -1.0 (клиппинг).
    TP в норме -> только fade_end (0 проходов: шаг в P18-бюджете 20 мин; полный
    mastering.master на часовом файле > 20 мин, run 40095684453 — timeout).
    TP > -1 или громкость I вне окна гейта -> loudnorm (run 40145954650: TP=-2.0, пропуск оставил I=-17.4 < -16 = FAIL). один проход loudnorm TP=-2 (EQ сегменты получили при записи в банк)."""
    import os
    import subprocess
    m = _music_mod()
    import mastering
    from quality_gate import LUFS_TARGET
    from quality_gate import MIN_I, MAX_I
    mi = mastering.measure(track)
    if mi["tp"] > -1.0 or not (MIN_I <= mi.get("i", -99.0) <= MAX_I):
        tmp = track + ".tp.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", track,
                        "-af", f"loudnorm=I={LUFS_TARGET:g}:TP=-2:LRA=11", "-c:a", "libmp3lame", "-b:a", "192k", tmp],
                       check=True)
        os.replace(tmp, track)
    m.fade_end(track)


def _norm_segments(paths: list[Path], log=print) -> None:
    """Сгладить внутренние LU-скачки сегмента ДО склейки (run 40155188504: 4.7 LU внутри
    одного сегмента -> 03c FAIL). Single-pass loudnorm (динамический режим) на каждом
    сегменте, тот же профиль, что master_final (I/TP/LRA); сегмент 180 с ~= секунды.
    ponytail: однопроходный loudnorm не так точен, как two-pass; при возврате FAIL на
    LU-скачках — перейти на two-pass с кэшем измерений в meta сегмента."""
    from quality_gate import LUFS_TARGET
    for p in paths:
        tmp = str(p) + ".ln.mp3"
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p),
                            "-af", f"loudnorm=I={LUFS_TARGET:g}:TP=-2:LRA=11",
                            "-c:a", "libmp3lame", "-b:a", "192k", tmp],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.getsize(tmp) > 0:
            os.replace(tmp, p)
        else:
            log(f"::warning::loudnorm {p.name} не удался, сегмент как есть: {(r.stderr or '').strip()[:160]}")


def assemble(paths: list[Path], run_dir: Path, metas: list[dict], genre: str, out: str = "track.mp3") -> dict:
    """Склейка сегментов банка тем же кодом, что час-микс (prep_segments + concat_tracks)."""
    m = _music_mod()

    seg = [{"name": e.get("name"), "seed": e.get("seed"), "prompt": e.get("prompt")} for e in metas]
    prompts = " | ".join(dict.fromkeys(str(e.get("prompt")) for e in metas))
    seed = int(metas[0].get("seed") or 0) if metas else 0

    _norm_segments(paths, log=print)
    m.prep_segments([str(p) for p in paths], log=print)
    durs = [m._probe_sec(p) for p in paths]
    m.concat_tracks([str(p) for p in paths], str(Path(run_dir) / out))
    master_final(str(Path(run_dir) / out), genre)
    chapters = m.chapters(durs, m.track_names(len(paths), seed), xfade=m.XFADE)
    seams = m.seam_times(durs)
    duration = int(sum(durs) - m.XFADE * (len(durs) - 1))
    meta = {"genre": genre, "prompt": prompts, "seed": seed, "duration": duration,
            "segments": seg, "chapters": chapters, "seams": seams, "bank": True}
    (Path(run_dir) / "music_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


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
