#!/usr/bin/env python3
"""Разметка владельца (t_ef393676, вердикт 20.10 по 4 A/B, коммит 84c67cf) + жалобы.

Единый источник истины для калибровки quality_gate:
- approved: ab_1, ab_3 (вердикт «вроде неплохие») + versija_1 (turbo_2, xl-probe
  run 39070953361, BLINDMAP versija_1=turbo_2) — эти треки гейт обязан пропускать;
- neutral: ab_0, ab_2 — без оценки, на калибровку не влияют;
- complaints: p-kkEmLGviU (phonk, 17.10) и tIJKpWrVzOM (lofi, 16.10) — гейт обязан
  браковать; замеры сняты с ушедших на YouTube файлов в момент жалоб.
"""
import os
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Позитивы владельца: файл + полные замеры (ebur128=peak=true, VPS 21.10).
# t_9944c9ce: пересозданы через новый мастер (LOFI_TP_TARGET=-4, адаптивный лимитер),
# старые замеры (TP -1.9..-2.2, LRA 3.7..5.4) не проходили новый гейт TP<=-3/LRA>=3.5.
APPROVED = {
    "ab_1": {"file": "calib_approved_ab1.mp3", "lra": 9.1, "i": -14.9, "tp": -4.6,
             "bands_rel": [-2.8, 0.0, -5.8, -4.3, -8.9, -16.2, -16.2, -19.8]},
    "ab_3": {"file": "calib_approved_ab3.mp3", "lra": 9.5, "i": -14.9, "tp": -4.3,
             "bands_rel": [-2.8, 0.0, -5.8, -4.3, -9.1, -16.2, -16.2, -19.8]},
    "versija_1": {"file": "calib_approved_versija1.mp3", "lra": 9.1, "i": -14.9, "tp": -4.4,
                  "bands_rel": [-2.8, 0.0, -5.7, -4.2, -8.9, -16.2, -16.1, -19.8]},
}
NEUTRAL = ("ab_0", "ab_2")
# Жалобы владельца (негатив). p-kkEmLGviU: замер 17.10 с YouTube-копии (300-420 с):
# LRA 1.0, мелодия 1-5 кГц утоплена, TP до +1.9 после AAC. tIJKpWrVzOM: lofi 16.10,
# «непонятные звуки после первых секунд» — брак хвоста, CE-окна 2.1-3.6.
COMPLAINTS = {
    "p-kkEmLGviU": {"genre": "phonk", "lra": 1.0,
                    "bands_rel": [0.3, 0.0, 2.0, 2.1, -2.9, -7.4, -5.1, -10.2]},
    "tIJKpWrVzOM": {"genre": "anime lofi", "lra": 4.2,
                    "bands_rel": [-2.0, 0.0, 3.1, -3.0, -12.5, -18.0, -19.5, -24.0]},
}


def approved_path(key: str) -> str:
    return str(FIXTURES / APPROVED[key]["file"])


if __name__ == "__main__":
    for k, v in APPROVED.items():
        p = approved_path(k)
        assert os.path.isfile(p) and os.path.getsize(p) > 100_000, p
        print(k, p, os.path.getsize(p))
