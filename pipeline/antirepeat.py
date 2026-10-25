#!/usr/bin/env python3
"""03d анти-повтор (спец t_b4006a6e п.3): chroma-схожесть трека с треками, опубликованными за 14 дней.

Отпечаток = ковариация 12 chroma-классов по всему треку (144 числа): не зависит от сдвига/громкости/перекодирования,
различает гармонию и тональность. Только numpy + ffmpeg (новых зависимостей нет).
Хранение: .state/antirepeat/<дата>_<videoId>.json (файл на выпуск: два жанра в сутки не конфликтуют при rebase),
CI коммитит через force-add; записи старше 14 дней удаляются при записи и игнорируются при сравнении.

Запуск:  antirepeat.py           03d: сравнить runs/<последний>/track.mp3; FAIL -> регенерация (03_music + 03c), повтор ->
                                 exit 1 (не публиковать).
         antirepeat.py --record  после 05 publish: сохранить отпечаток опубликованного трека.
"""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

WINDOW_DAYS = 14
# Pearson отпечатков. Замер 17.10 (ACE-Step 1.5, 4 варианта одного промпта + 4 сэмпла lofi): разные треки 0.13-0.86,
# тот же трек (сдвиг/громкость/перекодирование) >= 0.98.
# ponytail: глобальная гармония, не мелодия; ловит повтор трека/гармонии целиком. Выше точность = DTW по chroma-
# последовательности (хранить ~20 КБ/трек), добавить, если повторы мелодии в другой гармонии пройдут гейт.
THRESHOLD = 0.92
RETRIES = 1  # регенерация час-микса ~40 мин, job timeout 150 мин
SR, N, HOP = 11025, 4096, 11025 // 2
STATE = Path(__file__).resolve().parent.parent / ".state" / "antirepeat"


def fingerprint(path) -> np.ndarray:
    y = np.frombuffer(subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
                                      "-f", "f32le", "-"], capture_output=True, check=True).stdout, np.float32)
    fq = np.fft.rfftfreq(N, 1 / SR)
    ok = (fq > 55) & (fq < 2000)
    pc = (np.round(12 * np.log2(fq[ok] / 440)) % 12).astype(int)
    M = np.zeros((ok.sum(), 12), np.float32)
    M[np.arange(ok.sum()), pc] = 1
    frames = np.lib.stride_tricks.sliding_window_view(y, N)[::HOP]
    cov, n, win = np.zeros((12, 12)), 0, np.hanning(N).astype(np.float32)
    for i in range(0, len(frames), 256):  # блоками: час-микс не держим спектром в памяти целиком
        C = np.sqrt((np.abs(np.fft.rfft(frames[i:i + 256] * win, axis=1))[:, ok] ** 2) @ M)
        C /= np.linalg.norm(C, axis=1, keepdims=True) + 1e-9
        cov += C.T @ C
        n += len(C)
    return (cov / max(n, 1)).ravel()


def similarity(a, b) -> float:
    a, b = np.asarray(a, float) - np.mean(a), np.asarray(b, float) - np.mean(b)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def encode(fp):
    return [round(float(x), 5) for x in fp]


def decode(v):
    return np.asarray(v, float)


def load(state=STATE):
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(Path(state).glob("*.json"))]


def recent(entries, today):
    return [e for e in entries if (today - dt.date.fromisoformat(e["date"])).days < WINDOW_DAYS]


def check(fp, entries, today):
    """[(video, схожесть)] треков за 14 дней со схожестью > THRESHOLD; пусто = PASS."""
    hits = [(e["video"], similarity(fp, decode(e["fp"]))) for e in recent(entries, today)]
    return [h for h in hits if h[1] > THRESHOLD]


def record(state, fp, today, video, genre):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    for f in state.glob("*.json"):  # 14-дневное окно: старое удаляем, git add -f фиксирует удаление
        if (today - dt.date.fromisoformat(json.loads(f.read_text(encoding="utf-8"))["date"])).days >= WINDOW_DAYS:
            f.unlink()
    (state / f"{today}_{video}.json").write_text(json.dumps(
        {"date": str(today), "video": video, "genre": genre, "fp": encode(fp)}), encoding="utf-8")


def gate(track, entries, today, regen, retries=RETRIES, log=print) -> bool:
    """track() -> путь. FAIL -> regen() (новый трек, прошедший 03c, или None) до retries раз. True = публиковать."""
    path = track()
    for attempt in range(retries + 1):
        hits = check(fingerprint(path), entries, today)
        if not hits:
            log(f"antirepeat PASS: {path}")
            return True
        log(f"::error::antirepeat: трек похож на опубликованные {[(v, round(s, 3)) for v, s in hits]} > {THRESHOLD}")
        if attempt == retries:
            break
        log(f"antirepeat: регенерация {attempt + 1}/{retries}")
        path = regen()
        if path is None:
            log("::error::antirepeat: регенерированный трек не прошёл 03c quality gate")
            return False
    return False


def _regen():
    from common import latest_run_dir
    here = Path(__file__).parent
    # seed в 03_music = hash(run_dir.name), hash() рандомизирован на процесс -> новый процесс = новый трек
    subprocess.run([sys.executable, str(here / "03_music.py")], check=True, cwd=here)
    if subprocess.run([sys.executable, str(here / "quality_gate.py")], cwd=here).returncode:
        return None
    return latest_run_dir() / "track.mp3"


def main(argv):
    from common import latest_run_dir
    today, d = dt.datetime.now(dt.timezone.utc).date(), latest_run_dir()
    if "--record" in argv:
        pub = d / "published.json"
        if not pub.exists():
            print("antirepeat: нет published.json — не опубликовано, отпечаток не пишем")
            return 0
        genre = json.loads((d / "music_meta.json").read_text(encoding="utf-8"))["genre"]
        record(STATE, fingerprint(d / "track.mp3"), today, json.loads(pub.read_text())["id"], genre)
        print(f"antirepeat: отпечаток сохранён в {STATE}")
        return 0
    return 0 if gate(lambda: d / "track.mp3", load(), today, _regen) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
