#!/usr/bin/env python3
"""t_ba72c7aa R1: генератор банка сегментов. Музыка НЕ генерируется в слоте выпуска (владелец 21.10):
фоновый прогон кладёт в банк только сегменты, прошедшие гейт сегмента (тот же gated_gen, что в
03_music: best-of-3(+2), CE каждого окна >= MIN_CE, objective жанра). Банк = /app/output/bank/<жанр>
в контейнере ace-step (bind на C: dockerlocal/ace15/output, не D:). Выпуск = приоритет:
идёт/ждёт daily-video -> генератор уступает GPU и выходит; ace-step он НИКОГДА не рестартит
(рестарт убил бы задачу выпуска) — сбой задачи = выход, следующий прогон продолжит.
ponytail: сборка выпуска из банка = R2 (следующий PR); пока банк только наполняется."""
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
BANK_ROOT = "/app/output/bank"
CAP_FILES = 400  # ~4 МБ/сегмент -> ~1.6 ГБ, ниже лимита 15 ГБ спецификации
RELEASE_SEG = 20  # t_1f53095a R3: 1 выпуск = час = 20 x 180 с
TARGET_RELEASES = 2  # цель банка: >= 2 выпуска вперёд (40 сегментов)
BANK_LIMIT_KB = 15 * 1048576  # лимит банка 15 ГБ (все жанры, du -sk BANK_ROOT)
MARGIN = 4  # запас сегментов в группе сверх need: рваный cp бьёт пачкой — всплеск из 3 битых (39924822702) не должен обнулять выпуск


class BankYield(Exception):
    """ace-step завис, а рестарт банку запрещён: выйти чисто, банк сохранён, следующий прогон продолжит."""


def slug(genre: str) -> str:
    return genre.replace(" ", "-")


def fill(target, have, make, put, busy, log=print, max_iter=40, max_consecutive_fail=3, deadline=None,
         guard=None):
    """Наполнить банк до target. make(i) -> путь прошедшего гейт сегмента или None (брак).
    busy() = выпуск идёт/в очереди -> выход. Сбой генерации при занятом GPU = уступили, без ошибки.
    Сбой без выпуска (run 39884870081: oneMKL transient 0/21 на 39/40) = повтор, прогон роняем
    только после max_consecutive_fail сбоев подряд — устойчивая поломка остаётся ошибкой.
    deadline = monotonic-метка: после неё чистый выход (root-cause t_c10bb82c: runs 39693436157 /
    39821580626 — банк не следит за бюджетом джобы, 170 мин съедается на CE-гейтах CPU, GitHub
    режет джобу по таймауту и весь прогон впустую; банковские mp3 уже в контейнере, но хвост
    + логи/алерты теряются)."""
    n, i, fails = have(), 0, 0
    while n < min(target, CAP_FILES) and i < max_iter:
        if deadline and time.monotonic() > deadline:
            log(f"банк: бюджет джобы исчерпан — выхожу чисто (в банке {n})")
            break
        if busy():
            log(f"банк: выпуск в работе — уступаю GPU (в банке {n})")
            break
        why = guard() if guard else None  # t_1f53095a R3: лимит 15 ГБ / пол C: — до генерации, не после
        if why:
            log(f"банк: стоп — {why} (в банке {n})")
            break
        try:
            p = make(i)
        except BankYield as e:
            log(f"банк: {e} — выхожу чисто (в банке {n})")
            break
        except Exception as e:
            if busy():
                log(f"банк: сбой {type(e).__name__} во время выпуска — выхожу (в банке {n})")
                break
            fails += 1
            if fails >= max_consecutive_fail:
                raise
            log(f"банк: сбой {type(e).__name__} ({fails}/{max_consecutive_fail}) — повторяю: {e}")
            continue
        i += 1
        fails = 0
        if p and put(p) is not False:
            n += 1
            log(f"банк: +1 сегмент, всего {n}/{target}")
    return n


def reserve_level(n: int) -> str:
    """t_1f53095a R3: n = свободные совместимые сегменты. empty = выпуск пропустит слот (< MIN_SEG)."""
    from bank_release import MIN_SEG
    if n < MIN_SEG:
        return "empty"
    if n < RELEASE_SEG:
        return "low"
    if n < RELEASE_SEG * TARGET_RELEASES:
        return "below_target"
    return "ok"


def status_line(genre: str, n: int) -> str:
    lvl = reserve_level(n)
    s = f"банк {genre}: {n} сегм. = {n / RELEASE_SEG:.1f} выпуска (цель {TARGET_RELEASES})"
    if lvl in ("low", "empty"):
        s += " — меньше 1 выпуска, генератор в приоритет"
        if lvl == "empty":
            s += "; слот выпуска будет пропущен"
    return s


def guard_reason(bank_kb: int, disk_rc: int):
    """None = писать можно. bank_kb = du банка, disk_rc = код disk_gate.sh c (единый пол C:)."""
    if bank_kb >= BANK_LIMIT_KB:
        return f"банк {bank_kb / 1048576:.1f} ГБ >= лимита {BANK_LIMIT_KB // 1048576} ГБ"
    if disk_rc != 0:
        return "на C: ниже пола disk_floors.env (disk_gate.sh c)"
    return None


def disk_gate_rc(need_gb: int = 1) -> int:
    gate = HERE.parent / "deploy/gpu-pc/disk_gate.sh"
    return subprocess.run(["sh", str(gate), "c", str(need_gb)]).returncode


def bank_kb(docker_sh=None) -> int:
    out = (docker_sh or _docker)("exec", "ace-step", "sh", "-c", f"du -sk {BANK_ROOT} 2>/dev/null || echo 0")
    return int((out.split() or ["0"])[0])


def reserve_count(counts: dict) -> int:
    """Сколько сегментов выпуск реально наберёт: крупнейшая группа + совместимые с ней (как pick).
    ponytail: сумма по совместимым соседям, без учёта битых при take; точнее = прогнать pick()."""
    from bank_release import _keys_related
    return max((sum(c for k2, c in counts.items() if _keys_related(k, k2)) for k in counts), default=0)


def reserve_check(counts_by_genre: dict, send, dispatch) -> list:
    """Часовой отчёт: строка на жанр. < 1 выпуска = TG-алерт + dispatch bank-fill (генератор в приоритет)."""
    lines = [status_line(g, n) for g, n in counts_by_genre.items()]
    low = [status_line(g, n) for g, n in counts_by_genre.items() if reserve_level(n) in ("low", "empty")]
    for line in lines:
        print(line)
    if low:
        send("⚠️ " + "\n".join(low))
        dispatch()
    return lines


def dispatch_fill(repo=None, token=None) -> None:
    """Поднять генератор: bank-fill сейчас, если он не идёт и не ждёт (concurrency затёр бы pending)."""
    repo = repo or os.environ["GITHUB_REPOSITORY"]
    token = token or os.environ["GH_TOKEN"]
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    base = f"https://api.github.com/repos/{repo}/actions/workflows/bank-fill.yml"
    for st in ("in_progress", "queued", "pending", "waiting"):
        with urllib.request.urlopen(urllib.request.Request(f"{base}/runs?status={st}&per_page=1", headers=h),
                                    timeout=30) as r:
            if json.load(r).get("total_count", 0):
                print(f"bank-fill уже {st} — новый не ставлю")
                return
    req = urllib.request.Request(f"{base}/dispatches", method="POST", headers=h,
                                 data=json.dumps({"ref": os.environ.get("GITHUB_REF_NAME", "master")}).encode())
    urllib.request.urlopen(req, timeout=30).close()
    print("bank-fill запущен вне расписания (запас < 1 выпуска)")


def reserve_main() -> int:
    from common import tg_send
    counts = {}
    for g in ("anime lofi", "chill phonk"):
        try:
            counts[g] = reserve_count(group_counts(g, _docker))
        except Exception as e:
            print(f"bank {g}: не прочитан ({type(e).__name__}: {e})")
            counts[g] = 0
    reserve_check(counts, tg_send, dispatch_fill)
    try:
        print(f"банк на диске: {bank_kb() / 1048576:.2f} ГБ из {BANK_LIMIT_KB // 1048576}")
    except Exception as e:
        print(f"du банка: {type(e).__name__}")
    return 0


def _sh(*a):
    return subprocess.run(list(a), check=True, capture_output=True, text=True).stdout


def _docker(*a):
    """docker_sh для put_verified/group_counts: 26.10 голый _sh отдавал `cp ... ace-step:...`
    локальному cp (exit 1) — принятые гейтом сегменты не попадали в банк."""
    return _sh("docker", *a)


def release_busy(repo=None, token=None, sleep=time.sleep, tries=3) -> bool:
    """Идёт/ждёт ли daily-video. Сеть к GitHub API недоступна после повторов -> True (уступаем GPU,
    следующий прогон продолжит): падение банка из-за RemoteDisconnected — не ошибка генерации."""
    repo = repo or os.environ["GITHUB_REPOSITORY"]
    token = token or os.environ["GH_TOKEN"]
    for st in ("in_progress", "queued", "pending", "waiting"):
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/workflows/daily-video.yml/runs?status={st}&per_page=1",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        for k in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    if json.load(r).get("total_count", 0):
                        return True
                break
            except OSError as e:  # URLError/RemoteDisconnected/timeout
                print(f"банк: проверка выпуска {type(e).__name__}, попытка {k + 1}/{tries}")
                sleep(10 * (k + 1))
        else:
            return True
    return False


def restart_guard(busy, restart):
    """Рестарт ace-step банку разрешён, только если выпуска нет: иначе убьём его задачу.
    23.10: полный запрет оставил зависший ace-step (VAE на CPU) на 4 ч, банк 5 раз выходил пустым."""
    def guard(*a, **k):
        if busy():
            raise BankYield("ace-step не ответил, выпуск в работе — рестарт не делаю")
        print("банк: ace-step завис, выпуска нет — рестарт")
        return restart(*a, **k)
    return guard


def guarded_scores(paths, busy, batch):
    """Критик чистит общий /app/output/qg в ace-step: при выпуске он чужой -> не запускаем.
    Старт выпуска = чистый выход (BankYield), не RuntimeError: повторный busy() в fill мог
    вернуть False из-за гонки статусов API и уронить весь банк (run 39800222017)."""
    if busy():
        raise BankYield("выпуск стартовал — критик банка не запускаю")
    return batch(paths)


STATS_DAYS = 30  # t_fed47d5f R4: окно статистики брака
STATS_MAX_FAIL = 0.5  # брак > 50% кандидатов промпта за окно = промпт выключен
STATS_MIN_N = 6  # меньше кандидатов в окне = данных мало, промпт включён


def stats_path(genre: str) -> str:
    """stats.json рядом с сегментами: выпуск берёт только *.mp3 (bank_release.entries), файл ему невидим."""
    return f"{BANK_ROOT}/{slug(genre)}/stats.json"


def _ts(r) -> float:
    try:
        return float(r.get("ts", 0))
    except (TypeError, ValueError):
        return 0.0


def stats_load(genre, docker_sh):
    """Строки статистики [{prompt, seed, src, ok, why, ts}]. exec недоступен = None (не перезаписывать
    файл вслепую: потеря истории); битый/пустой JSON = [] (начинаем заново)."""
    try:
        raw = docker_sh("exec", "ace-step", "sh", "-c", f"cat {stats_path(genre)} 2>/dev/null || true")
    except Exception as e:
        print(f"bank: stats.json не прочитан ({type(e).__name__}: {e})")
        return None
    try:
        rows = json.loads(raw or "[]")
    except ValueError:
        print("bank: stats.json битый — статистика начата заново")
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def stats_flush(genre, rows, docker_sh, now=None) -> bool:
    """Дописать строки сегмента в stats.json (после КАЖДОГО сегмента), старше STATS_DAYS выкинуть.
    Запись атомарная: локальный tmp -> docker cp .part -> mv. Писатель один (bank-fill concurrency)."""
    now = now or time.time()
    old = stats_load(genre, docker_sh)
    if old is None:
        return False
    keep = [r for r in old + list(rows) if now - _ts(r) < STATS_DAYS * 86400]
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(keep, f, ensure_ascii=False)
        dst = stats_path(genre)
        docker_sh("cp", tmp, f"ace-step:{dst}.part")
        docker_sh("exec", "ace-step", "mv", f"{dst}.part", dst)
        return True
    finally:
        os.unlink(tmp)


def fail_rate(rows, prompt, now=None, days=STATS_DAYS):
    """(доля брака, n) кандидатов промпта за последние days дней; n == 0 -> (None, 0)."""
    now = now or time.time()
    win = [r for r in rows if r.get("prompt") == prompt and now - _ts(r) < days * 86400]
    if not win:
        return None, 0
    return sum(1 for r in win if not r.get("ok")) / len(win), len(win)


def prompt_enabled(rows, prompt, now=None, max_fail=STATS_MAX_FAIL, min_n=STATS_MIN_N) -> bool:
    """R4: брак > max_fail за 30 дней = промпт выключен; меньше min_n кандидатов = включён."""
    rate, n = fail_rate(rows, prompt, now)
    return n < min_n or rate <= max_fail


def enabled_variants(variants, rows, now=None):
    """Варианты без выключенных статистикой; выключены все -> все (генерация не останавливается)."""
    on = [v for v in variants if prompt_enabled(rows, v, now)]
    if len(on) < len(variants):
        print(f"bank: статистика брака выключила {len(variants) - len(on)} из {len(variants)} промптов"
              + ("" if on else " — выключены все, беру без фильтра"))
    return on or list(variants)


def choose_prompt(variants, counts, need, day_prompt, key):
    """Выпуск берёт need сегментов одной группы (bpm, key). Ротация промпта по дню размазывала банк
    по группам -> ни одной полной (run 39800343057, nobank). Добиваем самую большую незакрытую группу;
    все закрыты/пусто -> промпт дня (разнообразие следующего выпуска)."""
    open_ = [v for v in variants if 0 < counts.get(key(v), 0) < need]
    return max(open_, key=lambda v: counts[key(v)]) if open_ else day_prompt


def effective_target(target, have, counts, need):
    """Цель по общему числу файлов слепа к группам: 40/40 при группе 21 из need=20 и 2 битых ->
    nobank, генератор стоит (run 39905560585). Растим цель, пока в одной группе нет need+MARGIN."""
    gap = need + MARGIN - max(counts.values(), default=0)
    return max(target, have + gap) if gap > 0 else target


def pin_prompt(prompt, counts, need, seed):
    """Жанр без «NN BPM, X major» в промпте (chill phonk): bpm/key брались из seed КАЖДОГО сегмента ->
    банк размазан по группам, 20 совместимых не набрать (слоты phonk 22-23.10 все nobank).
    Фиксируем пару в тексте: добиваем самую большую незакрытую группу, иначе пара из seed."""
    import importlib.util as _u
    spec = _u.spec_from_file_location("music_pin", HERE / "03_music.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    if m.prompt_bpm(prompt) and m.prompt_key(prompt):
        return prompt
    open_ = [k for k, n in counts.items() if k[0] and k[1] and 0 < n < need]
    bpm, key = max(open_, key=counts.get) if open_ else (70 + seed % 21, m.ACE15_KEYS[seed % len(m.ACE15_KEYS)])
    return f"{prompt}, {bpm} BPM, {key}"




def _sha_local(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha_container(d, name, docker_sh):
    # exec недоступен = проверить нельзя = сегмент не кладём (None)
    try:
        out = docker_sh("exec", "ace-step", "sh", "-c", "sha256sum " + d + "/" + name + " 2>/dev/null")
        return out.split()[0] if out.split() else None
    except Exception:
        return None


def put_verified(p, genre, name, meta, docker_sh, tries=2) -> bool:
    from bank_release import MAX_SWING_DB, internal_swing
    lo, hi = internal_swing(p)
    if hi - lo > MAX_SWING_DB:
        print(f"::warning::банк {genre}: {name} отклонён (внутренний провал {hi - lo:.1f} дБ > {MAX_SWING_DB})")
        return False
    """docker cp на ПК бывает рваный в ОБЕ стороны (23.10: два слота по 5 битых из группы =>
    nobank при MARGIN 4). json+mp3 кладутся во временное имя (.part), sha256 контейнера
    сверяется с локальным, затем атомарный mv; не сошлось после ретраев - сегмент НЕ в банк
    (False), генератор кладёт следующий."""
    import json as _json
    from pathlib import Path as _P
    d = f"{BANK_ROOT}/{slug(genre)}"
    stem = name[:-4] if name.endswith(".mp3") else name
    local_json = _P(p).with_name(stem + ".json")
    local_json.write_text(_json.dumps(meta, ensure_ascii=False))
    pairs = [(local_json, f"{stem}.json"), (_P(p), f"{stem}.mp3")]
    try:
        try:
            for src, remote in pairs:
                local_sha = _sha_local(src)
                for _attempt in range(1, tries + 1):
                    docker_sh("cp", str(src), f"ace-step:{d}/{remote}.part")
                    if _sha_container(d, f"{remote}.part", docker_sh) == local_sha:
                        break
                else:
                    print(f"bank: sha256 не сошёлся после {tries} cp ({remote}) - сегмент пропущен")
                    return False
            for _src, remote in pairs:  # mp3 последним: есть mp3 = есть проверенный json
                docker_sh("exec", "ace-step", "mv", f"{d}/{remote}.part", f"{d}/{remote}")
            return True
        except Exception as e:
            print(f"bank: put {type(e).__name__}: {e} stderr={getattr(e, 'stderr', '')!r} - сегмент пропущен")  # 26.10: phonk cp exit 1 без причины
            return False
    finally:
        local_json.unlink(missing_ok=True)


def group_counts(genre, docker_sh, now=None):
    """Свободные (не использованные 14 дней) сегменты банка по группам (bpm, key)."""
    import bank_release as br
    used = []
    try:
        used = (br.ROOT / ".state/bank_used.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        pass
    skip = br._used_filter(used, now or time.time())
    out = {}
    d = br.bank_dir(genre)
    bad = []  # 24.10: битые учитывались в группах -> fill кормил «полную» группу, а take() её же карантинил (круговое голодание F major, t_ba72c7aa)
    # 26.10: быстрые lofi (>LOFI_MAX_BPM) выпуск не берёт -> в группы не считаем, иначе банк «полон» и fill стоит
    for e in br.energy_ok(br.entries(genre, docker_sh=docker_sh), genre):
        n = e["name"]
        if n in skip:
            continue
        ok = False
        try:
            r = docker_sh("exec", "ace-step", "sh", "-c",
                          f"ffprobe -v error -show_entries format=duration -of csv=p=0 {d}/{n}.mp3 2>/dev/null")
            ok = bool(r.strip() and float(r.strip().split()[0]) > 1.0)
        except Exception:
            ok = False
        if not ok:
            bad.append(n)
            docker_sh("exec", "ace-step", "sh", "-c",
                      f"mkdir -p {d}/broken && mv -f {d}/{n}.mp3 {d}/{n}.json {d}/broken/")
            continue
        k = br.group_key(e)
        out[k] = out.get(k, 0) + 1
    if bad:
        print(f"bank: карантин групп-каунта: {len(bad)} битых -> {sorted(bad)[:6]}...")
    return out


def main(max_iter=40, busy=None):
    """Один прогон наполнения -> (в банке, цель). bank_fill_worker зовёт max_iter=1: сегмент в банке
    до следующей генерации, группы/промпт/статистика пересчитываются на каждый сегмент."""
    busy = busy or release_busy
    genre = os.environ.get("GENRE", "anime lofi")
    target = int(os.environ.get("BANK_TARGET", "30"))
    d = f"{BANK_ROOT}/{slug(genre)}"
    _sh("docker", "exec", "ace-step", "mkdir", "-p", d)

    def have():
        out = _sh("docker", "exec", "ace-step", "sh", "-c", f"ls {d} | grep -c mp3$ || true")
        return int(out.strip() or 0)

    spec = importlib.util.spec_from_file_location("music_bank", HERE / "03_music.py")
    music = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(music)

    music.ace_restart = restart_guard(busy, music.ace_restart)

    from quality_gate import ce_windows_batch, objective
    prompt, ref = music.GENRE_PROMPTS[genre], os.environ.get("ACE15_REF_AUDIO") or None
    seed = random.randrange(2**31)
    need = -(-int(os.environ.get("TRACK_DURATION_SEC", "3600")) // 180)
    stats = stats_load(genre, _docker) or []  # R4: читаем ДО выбора промпта сегмента
    if genre != "anime lofi":  # refpool = семейство ab_1/ab_3 + эталоны только для lofi; phonk одобрен noref
        try:
            counts = group_counts(genre, _docker)
        except Exception as e:
            print(f"bank: группы не прочитаны ({type(e).__name__}: {e})")
            counts = {}
        base = prompt
        prompt = pin_prompt(base, counts, need + MARGIN, seed)
        if not prompt_enabled(stats, prompt):  # R4: группа выключена браком -> пара из seed
            alt = pin_prompt(base, {}, need + MARGIN, seed)
            print(f"bank: промпт ...{prompt[-24:]} выключен статистикой брака -> ...{alt[-24:]}")
            prompt = alt
        target = effective_target(target, have(), counts, need)
        print(f"bank {genre}: группы {counts} -> промпт ...{prompt[-24:]}, цель {target}")
    try:
        if genre != "anime lofi":
            raise LookupError("refpool только для anime lofi")
        import refpool
        pair = refpool.pick()
        variants = enabled_variants(refpool.PROMPT_VARIANTS, stats)  # R4: выключенные браком не берём
        day = pair["prompt"] if pair["prompt"] in variants else variants[0]
        try:
            counts = group_counts(genre, _docker)
            prompt = choose_prompt(variants, counts, need + MARGIN, day,
                                   lambda v: (music.prompt_bpm(v), music.prompt_key(v)))
            target = effective_target(target, have(), counts, need)
            print(f"bank: группы {counts}, нужно {need}+{MARGIN} -> промпт {prompt[-30:]}, цель {target}")
        except Exception as e:  # листинг банка недоступен -> промпт дня
            print(f"bank: группы не прочитаны ({type(e).__name__}: {e}); промпт дня")
            prompt = day
        refpool.ensure_ref(pair)
        ref = pair["ref_path"]
    except LookupError:
        pass
    except Exception as e:  # как в 03_music: эталон дня недоступен -> ref1
        print(f"refpool: {type(e).__name__}: {e}; fallback ref1")
    if ref and not Path(ref).is_file():
        ref = None
    run_dir = Path(tempfile.mkdtemp(prefix="bank_"))
    def scores(paths):
        return guarded_scores(paths, busy, ce_windows_batch)

    pending = []  # R4: исходы кандидатов текущего сегмента

    def record(p, ok, why):
        pending.append({"prompt": prompt, "seed": seed, "src": Path(p).name, "ok": bool(ok),
                        "why": why, "ts": int(time.time())})

    gated = music.gated_gen(music.mix_raw(run_dir, prompt, seed, ref, genre),
                            scores, lambda p: objective(p, genre)[0], attempts=3, extra=2, record=record)

    def gen(i):
        """Сегмент + stats.json после него. Сбой записи статистики банк не роняет.
        ponytail: промпт фиксирован на прогон (<=150 мин), выключение подхватит следующий прогон."""
        try:
            return gated(i)
        finally:
            if pending:
                try:
                    stats_flush(genre, pending, _docker)
                except Exception as e:
                    print(f"::warning::bank: stats.json не записан ({type(e).__name__}: {e})")
                pending.clear()

    def put(p):
        name = f"{int(time.time())}_{seed}_{Path(p).stem}"
        meta = {"genre": genre, "prompt": prompt, "ref": ref, "seed": seed,
                "src": Path(p).name, "ts": int(time.time())}
        # sha256 после cp (put_verified): рваный docker cp не попадает в банк (23.10)
        ok = put_verified(p, genre, name + ".mp3", meta, _docker)
        Path(p).unlink(missing_ok=True)
        return ok

    dmin = float(os.environ.get("BANK_DEADLINE_MIN", "0") or 0)
    deadline = time.monotonic() + dmin * 60 if dmin else None
    def guard():
        try:
            kb = bank_kb()
        except Exception:
            kb = 0  # du недоступен: лимит не проверить, пол C: проверяется всё равно
        return guard_reason(kb, disk_gate_rc())

    try:
        n = fill(target, have, gen, put, busy, max_iter=max_iter, deadline=deadline, guard=guard)
    finally:
        import shutil
        shutil.rmtree(run_dir, ignore_errors=True)  # воркер вечный: tmp не копится
    print(f"банк {genre}: {n} сегментов (цель {target})")
    return n, target


if __name__ == "__main__":
    if "--reserve" in sys.argv:
        sys.exit(reserve_main())
    main()
