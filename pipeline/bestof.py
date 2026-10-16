#!/usr/bin/env python3
"""Best-of-N по CE-критику (t_b4006a6e): N кандидатов на запрос -> лучший по min-CE audiobox.

Чистая логика без сети: генерация (gen) и CE (scores) передаются снаружи —
тестируется с фейками, в проде gen=03_music.generate_track_v15, scores=quality_gate.
CE логируется вызывающей стороной в music_meta.json (bestof -> {"ce": [...], "picked": i}).
ponytail: min из 3 отрывков (10/50/90%) — консервативно (брак в середине не спрячешь);
апгрейд — среднее, когда рефы/BPM-разброс дадут данные.
"""
from __future__ import annotations


def best_of(n: int, gen, scores, log=print) -> tuple[int, object, list[list[float]]]:
    """gen(i)->path, scores(paths)->[[c1,c2,c3], ...] по одному на кандидата.
    Возврат: (индекс лучшего, путь, все CE-строки). Ошибка критика = ошибка шага:
    вслепую выбирать нельзя, а молча брать первого — это не best-of."""
    paths = [gen(i) for i in range(n)]
    all_ce = scores(paths)
    if len(all_ce) != len(paths):
        raise RuntimeError(f"критик вернул {len(all_ce)}/{len(paths)} оценок: {all_ce!r}")
    mins = [min(c) for c in all_ce]
    best = min(range(n), key=lambda i: mins[i])
    log(f"best-of-{n}: CE(min)={[round(m, 2) for m in mins]} -> #{best + 1}")
    return best, paths[best], all_ce
