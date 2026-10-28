#!/usr/bin/env python3
"""t_5379ffee: «RuntimeError: микс 0 с < 900 с (15 мин) после выбраковки сегментов: 0 трек(ов)»
(runs 39152042720, 39155227095, 39170008194, 18-19.10, chill phonk). Причина: выпуск генерировал
час-микс вживую (03_music.plan_mix + gated_gen, ACE15_BESTOF=3), гейт сегмента браковал 3/3
кандидатов каждого сегмента (полосы/баланс к эталону) -> 0 треков -> выпуск падал.
Класс закрыт архитектурой f36cceb (t_ba72c7aa): выпуск собирается только из банка уже прошедших
гейт сегментов, генерация вынесена в bank-fill; нехватка банка = пропуск слота rc=2 + TG-алерт.
Инвариант: daily-video не возвращается к живой генерации, bank_release при пустом банке не падает."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
WF = (HERE.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")


def _step(name):
    s = WF[WF.index(f"name: {name}"):]
    nxt = s.find("- name:", 1)
    return s if nxt < 0 else s[:nxt]


def test_release_step_uses_bank_not_live_mix():
    step = _step("03 music")
    assert "bank_release.py" in step, "шаг 03 music не собирает выпуск из банка"
    assert "03_music.py" not in step, "выпуск снова генерирует микс вживую: вернётся «после выбраковки сегментов»"


def test_empty_bank_skips_slot_not_raises():
    """Вход упавших прогонов: гейт выбраковал всё -> в банке нет сегментов. Ожидаем rc=2, не RuntimeError."""
    import bank_release
    orig = bank_release.take, bank_release.disk_gate_rc
    bank_release.take = lambda *a, **k: None
    bank_release.disk_gate_rc = lambda *a, **k: 0
    try:
        assert bank_release.main([]) == 2
    finally:
        bank_release.take, bank_release.disk_gate_rc = orig
    step = _step("03 music")
    assert '"$rc" = 2' in step and "nobank=1" in step, "rc=2 (банк пуст) не обрабатывается как пропуск слота"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
            print("ok", n)
