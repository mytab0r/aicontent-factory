#!/usr/bin/env python3
"""Best-of-N через quality_gate (t_b4006a6e): N кандидатов -> лучший СРЕДИ ПРОШЕДШИХ гейт.

Правило владельца (16.10): каждый кандидат идёт через quality_gate (LRA, полосы, CE) ->
берём лучшего прошедшего; 0 прошло = перегенерация, до 3 раундов, потом ошибка шага
(daily-video шлёт TG-алерт по failure()). Порог и направление CE — из quality_gate.MIN_CE
(audiobox Content Enjoyment: БОЛЬШЕ = лучше; рефы ниши 7.07-7.91, брак 2.1-3.6).
Чистая логика: gen/scores/objective передаются снаружи, тест — фейки с реальными числами.
ponytail: min из 3 отрывков (10/50/90%) — брак в середине не спрячешь; апгрейд — среднее.
"""
from __future__ import annotations

from quality_gate import MIN_CE

ROUNDS = 3


def best_of(n: int, gen, scores, objective=lambda p: [], log=print, rounds: int = ROUNDS):
    """gen(k)->path, scores(paths)->[[c,c,c], ...], objective(path)->[причины FAIL] (пусто = OK).
    Возврат: (номер победителя, путь, строки по всем кандидатам).
    Ошибка критика = ошибка шага: вслепую выбирать нельзя."""
    rows = []
    for r in range(rounds):
        paths = [gen(r * n + i) for i in range(n)]
        ce = scores(paths)
        if len(ce) != len(paths):
            raise RuntimeError(f"критик вернул {len(ce)}/{len(paths)} оценок: {ce!r}")
        for i, (p, c) in enumerate(zip(paths, ce)):
            why = list(objective(p)) + ([f"CE {min(c):.2f} < {MIN_CE}"] if min(c) < MIN_CE else [])
            rows.append({"cand": r * n + i, "path": str(p), "ce": c, "ce_min": min(c), "fail": why})
        ok = [x for x in rows if not x["fail"]]
        log(f"best-of-{n} раунд {r + 1}: CE(min)={[round(min(c), 2) for c in ce]}, прошли гейт: {len(ok)}")
        if ok:
            best = max(ok, key=lambda x: x["ce_min"])
            log(f"-> #{best['cand'] + 1}, CE(min)={best['ce_min']:.2f}")
            return best["cand"], best["path"], rows
    raise RuntimeError(f"best-of-{n}: 0 кандидатов прошли quality_gate за {rounds} раунда: "
                       f"{[(x['cand'], x['fail']) for x in rows]}")
