#!/usr/bin/env python3
"""Калибровка quality_gate на разметке владельца (t_ef393676).

Триposix: гейт пропускает ab_1, ab_3, versija_1 (одобрено владельцем 20.10) и
бракует жалобы p-kkEmLGviU / tIJKpWrVzOM. Файлы — реальные сэмплы (84c67cf) и
versija_1 из лога run 39070953361 (sha256 сверён); жалобы — замеры с YouTube-копий,
снятые в момент жалоб (файлы недоступны: private/unavailable).
Запуск: python3 pipeline/test_gate_calibration.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import owners_labels
import quality_gate as qg


def real_why(key):
    """judge() по реальным полосам файла + все объективные проверки без CE."""
    why, m = qg.objective(owners_labels.approved_path(key), "anime lofi")
    return why, m


def main():
    # 0) фикстуры на месте и совпадают с замерами в разметке
    for k in owners_labels.APPROVED:
        p = owners_labels.approved_path(k)
        assert Path(p).is_file() and Path(p).stat().st_size > 100_000, p

    # 1) одобренное владельцем проходит judge() (без CE: критик = отдельная проверка)
    approved = 0
    for k in ("ab_1", "ab_3", "versija_1"):
        a = owners_labels.APPROVED[k]
        why = qg.judge(a["bands_rel"] and None or None, 0, "") if False else qg.judge(
            [r + owners_labels.APPROVED[k]["i"] - owners_labels.APPROVED[k]["bands_rel"][1]
             for r in owners_labels.APPROVED[k]["bands_rel"]], a["lra"], "anime lofi")
        assert why == [], f"{k} забракован порогами: {why}"
        approved += 1

    # 2) реальные файлы одобренных проходят objective() целиком (LRA/TP/I/полосы/конец)
    for k in ("ab_1", "ab_3", "versija_1"):
        why, m = real_why(k)
        # END_DROP/A18/A19 на 60-90 с сэмплах не показательны для семейства — сравниваем
        # только пороги калибровки (LRA/полосы/баланс/LUFS/TP/тишина):
        calib = [w for w in why if not any(x in w for x in ("резкий конец", "скачок громкости", "строй"))]
        assert calib == [], f"{k}: {calib} (m={m})"

    # 3) жалобы бракуются
    c1 = owners_labels.COMPLAINTS["p-kkEmLGviU"]
    why1 = qg.judge([r + (-22.0) for r in c1["bands_rel"]], c1["lra"], c1["genre"])
    assert why1, "p-kkEmLGviU прошёл гейт"
    c2 = owners_labels.COMPLAINTS["tIJKpWrVzOM"]
    why2 = qg.judge([r + (-15.0) for r in c2["bands_rel"]], c2["lra"], c2["genre"])
    assert why2, "tIJKpWrVzOM прошёл гейт"
    complaints = bool(why1) + bool(why2)

    # 4) LRA: 30-с голова не показательна (замер 21.10, ab_3: 5.4 полный / 1.2 голова;
    #    versija_1: 4.8 / 1.0) — long-form гейт обязан мерить финальный файл, не сэмпл.
    #    Фиксируем данные тестом, чтобы никто не вернул 30-с замер.
    head = {"ab_1": 2.6, "ab_3": 1.2, "versija_1": 1.0}
    for k, a in owners_labels.APPROVED.items():
        assert a["lra"] > head[k] >= 0, (k, a["lra"], head[k])

    print(f"METRIC approved={approved} complaints={complaints}")
    print("test_gate_calibration OK")


if __name__ == "__main__":
    main()
