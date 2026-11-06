#!/usr/bin/env python3
"""t_ba72c7aa follow-up 24.10 (run 40116619895): слот выпуска не должен ронять ACE-шаг, когда
контейнер running и его REST /health отвечает 200, но docker-healthcheck ещё starting (модели
догружаются до 15-20 мин). Выпуск генерацию не делает: ему нужны docker exec/cp (банк) и критик
03c (audiobox в контейнере). Контракт: здоровый сервис = /health 200; healthy-цикл = фолбэк, не стена.
"""
import re
from pathlib import Path

WF = (Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")
UP = WF[WF.index("name: ACE-Step up"):WF.index("name: 03 music")]


def test_slot_accepts_running_with_http_health():
    """ACE-шаг выходит 0, если сервис жив (внутриконтейнерный /health = 200), не дожидаясь healthy."""
    assert "health-proxy-probe" in UP, "нет прокси-пробы /health: слот падает на health=starting при живом сервисе"
    probe = [l for l in UP.splitlines() if "docker exec ace-step" in l and "urlopen" in l]
    assert probe, "проба живости сервиса (внутриконтейнерный /health) отсутствует"
    assert "exit 0" in UP[UP.index("health-proxy-probe"):], "проба не продолжает слот"


def test_health_loop_falls_back_to_proxy_not_error():
    """После healthy-цикла: пробуем прокси-пробу; только если и она лежит — ошибка с диагностикой."""
    tail = UP[UP.index("for i in $(seq 1 180)"):]
    assert "health-proxy-probe" in tail, "фолбэка /health после цикла нет"
    assert tail.index("health-proxy-probe") < tail.index("::error::ace-step не healthy"), \
        "ошибка должна идти после прокси-пробы"


def test_bank_fill_keeps_strict_health():
    """Генератор (bank-fill) по-прежнему требует docker-healthy: он шлёт задачи в очередь GPU."""
    bf = (Path(__file__).resolve().parent.parent / ".github/workflows/bank-fill.yml").read_text(encoding="utf-8")
    assert bf.count("= healthy ]") >= 1, "bank-fill lost strict health wait"


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for f in fns:
        try:
            f()
            print("ok", f.__name__)
        except AssertionError as e:
            print("FAIL", f.__name__, e); sys.exit(1)
    print(f"PASS {len(fns)}")
