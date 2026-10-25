#!/usr/bin/env python3
"""A/B-выборка G1zm0 (t_d53850f6): 4 кандидата на 4 РАЗНЫХ эталонах пула.

Зачем: смена звука (эталон/промпт) в прод допускается только после того,
как владелец прослушал варианты (sample gate). Скрипт генерирует N 60-с
кандидатов с разными эталонами (day + offset), гейтит их тем же критиком,
что прод, пишет manifest.json (эталон, промпт, сид, метрики) и ОБЯЗАТЕЛЬНО
LOCK-файл: публикация любого из них отдельным пайплайном запрещена до
явного решения владельца (LOCK существует -> publish отказывает).

Запуск в exp-workflow (без 05_publish):  ab_samples.py --n 4
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import refpool


def pick_variants(n=4, now=None) -> list[dict]:
    """n разных эталонов подряд от дня (соседние дни = разные пары по refpool.pick)."""
    base = refpool._day_epoch(now)
    out = []
    for off in range(n):
        e = refpool.pick(now=dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
                         + dt.timedelta(days=base + off))
        out.append(e)
    return out


def make_lock(run_dir: Path, meta: dict) -> Path:
    """LOCK = публикация variants этого run запрещена до вердикта владельца."""
    lock = Path(run_dir) / "ab_LOCK.json"
    lock.write_text(json.dumps({"locked": True, "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                                "reason": "A/B варианты ждут вердикта владельца (sample gate)",
                                **meta}, ensure_ascii=False, indent=2), encoding="utf-8")
    return lock


def generate(run_dir: Path, n=4, seg_sec=60) -> dict:
    from common import tg_send
    from mastering import master

    from quality_gate import ce_windows_batch, objective

    run_dir.mkdir(parents=True, exist_ok=True)
    from03 = _music()
    variants = pick_variants(n)
    rows = []
    for i, v in enumerate(variants):
        ref = refpool.ensure_ref(v)
        out = run_dir / f"ab_{i}_{v['yt_id']}.mp3"
        try:
            from03.generate_track_v15(v["prompt"], seg_sec, 9000 + i * 7, out,
                                      ref_audio=str(ref))
            master(out, out, genre="anime lofi")
            ce = ce_windows_batch([str(out)])[0]
            why, mtr = objective(str(out), "anime lofi")
            ce_ok = min(ce) >= _music_min_ce()
            rows.append({"i": i, "yt_id": v["yt_id"], "author": v["author"], "title": v["title"],
                         "prompt": v["prompt"], "seed": 9000 + i * 7, "ce_min": round(min(ce), 2),
                         "gate_ok": not why and ce_ok, "why": why, "metrics": mtr, "file": out.name})
        except Exception as e:  # один эталон недоступен = не валим остальные варианты
            rows.append({"i": i, "yt_id": v["yt_id"], "error": str(e)[:200]})
        (run_dir / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
    passed = [r for r in rows if r.get("gate_ok")]
    if not passed:
        tg_send("A/B: ни один из %d вариантов не прошёл критик — варианты не отправлены" % n)
        raise SystemExit("0 из %d прошли гейт" % n)
    make_lock(run_dir, {"n": n})
    return {"rows": rows, "dir": str(run_dir)}


def _music():
    import importlib.util
    spec = importlib.util.spec_from_file_location("music03", Path(__file__).parent / "03_music.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _music_min_ce() -> float:
    from quality_gate import MIN_CE
    return MIN_CE


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--seg-sec", type=int, default=60)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    run_dir = Path(a.out) if a.out else _music().Path("runs") / ("ab_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S"))
    res = generate(run_dir, n=a.n, seg_sec=a.seg_sec)
    ok = [r for r in res["rows"] if r.get("gate_ok")]
    print(json.dumps({"dir": res["dir"], "passed": len(ok), "rows": res["rows"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
