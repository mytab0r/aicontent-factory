#!/usr/bin/env python3
"""t_ba72c7aa R5: генерация удалена из слота публикации. daily-video НЕ содержит env генерации
(ACE15_MIX_BUDGET_SEC/BESTOF/SEG_EXTRA/REF_AUDIO), музыка = сборка из банка (bank_release.py);
каждый шаг после music гейтится steps.music.outputs.nobank (пустой банк = скип слота, не публикация).
Бюджеты генерации проверяются в bank-fill.yml (тест ниже)."""
import re
from pathlib import Path

WF = (Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")
def test_no_generation_env_in_daily_video():
    """R5: слот публикации не генерирует — env генерации удалены, музыка из банка."""
    for var in ("ACE15_MIX_BUDGET_SEC", "ACE15_BESTOF", "ACE15_SEG_EXTRA"):
        assert var not in WF, f"{var} остался в daily-video — генерация в слоте не удалена (R5)"
    assert "bank_release.py" in WF, "03 music не собирает из банка (R2)"
    # пустой банк -> скип слота: все шаги после music гейтятся nobank
    after = WF.split("- name: 03 music", 1)[1]
    for step in ("03c quality gate", "03d anti-repeat", "04 assemble", "04b quality gate final",
                 "05 publish", "05b anti-repeat record", "07 shorts", "TG report"):
        block = after.split(f"- name: {step}", 1)
        assert len(block) == 2, f"шаг не найден: {step}"
        head = block[1].split("run:", 1)[0]
        assert "nobank" in head, f"шаг {step} не гейтится nobank — пустой банк не пропускает слот"


def test_bank_fill_generator_budget():
    """R1: бюджет/отбор генерации переехали в bank-fill.yml; банк >= 2 выпуска (R3)."""
    bf = (Path(__file__).resolve().parent.parent / ".github/workflows/bank-fill.yml").read_text()
    m = re.search(r'BANK_TARGET:\s*"?(\d+)', bf)
    assert m and int(m.group(1)) >= 40, "BANK_TARGET < 40 = меньше 2 выпусков вперёд (R3)"
    assert "disk_gate" in bf, "банк наполняется без гейта диска C: (правило диска)"
    assert re.search(r'ACE15_BESTOF:\s*"?\d+', bf), "отбор best-of не задан в генераторе банка"


def test_refpool_ytdlp_in_venv():
    deps = WF.split("- name: install deps", 1)[1].split("- name:", 1)[0]
    assert "yt-dlp" in deps, "refpool зовёт yt-dlp из .venv — без него эталон дня всегда fallback"


def test_nobank_alerts_telegram():
    """P20 (аудит 23.10): run 23.10 01:30 success за 4 мин, nobank=1, publish не шёл, только ::warning —
    0 public за 7 дней, а статус зелёный. Пустой банк обязан слать TG-алерт, не молчать."""
    steps = WF.split("- name: ")
    alert = [s for s in steps if "steps.music.outputs.nobank == '1'" in s.split("run:", 1)[0]]
    assert alert, "нет шага с if: nobank == '1' — пропуск слота молчит (P20)"
    body = alert[0]
    assert "tg_send" in body and "TG_BOT_TOKEN" in body, "шаг nobank не шлёт TG-алерт (P20)"


if __name__ == "__main__":
    test_no_generation_env_in_daily_video()
    test_bank_fill_generator_budget()
    test_refpool_ytdlp_in_venv()
    test_nobank_alerts_telegram()
    print("ok")
