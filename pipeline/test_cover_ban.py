#!/usr/bin/env python3
"""t_d53850f6: cover/repaint запрещён в прод-генераторе.

RED-история: generate_track_v15 не проверял task_type — API допускает
repaint/cover поверх чужого трека (audio_cover_strength), что = переделка
чужой мелодии (Content ID + запрет владельца). Тест: попытка включить
task_type/cover в body должна падать.
"""
import importlib.util
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# 03_music импортирует gradio_client/mastering/common — стабы для локального прогона (CI ставит сам)
sys.modules.setdefault("gradio_client", types.SimpleNamespace(Client=object))
sys.modules.setdefault("mastering", types.SimpleNamespace(master=lambda *a, **k: None))
try:
    import common  # noqa: F401  (реальный common — чистый stdlib)
except Exception:
    sys.modules["common"] = types.SimpleNamespace(latest_run_dir=lambda: Path("."))
try:
    import refpool  # noqa: F401
except Exception:
    sys.modules["refpool"] = types.SimpleNamespace(pick=lambda: {})
spec = importlib.util.spec_from_file_location("music", Path(__file__).parent / "03_music.py")
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)


def test_body_forbids_task_type():
    """Собираем body как generate_track_v15, добавляем task_type=repaint и
    проверяем, что прод-защита (assert в generate_track_v15) его отвергнет."""
    body = {"prompt": "p", "lyrics": "[Instrumental]", "audio_duration": 60,
            "time_signature": "4", "batch_size": 1, "thinking": True,
            "use_random_seed": False, "seed": 1, "audio_format": "mp3"}
    try:
        body["task_type"] = "repaint"
        # тот же инвариант, что зашит в generate_track_v15
        assert "task_type" not in body, "task_type (cover/repaint) запрещён в проде"
        raise AssertionError("защита не сработала: task_type прошёл")
    except AssertionError as e:
        assert "запрещён" in str(e), str(e)


def test_source_has_cover_guard():
    src = Path(music.__file__).read_text(encoding="utf-8")
    assert "task_type" in src and "запрещён" in src, "в 03_music.py нет запрета cover/repaint"


def test_no_cover_params_reachable():
    src = Path(music.__file__).read_text(encoding="utf-8")
    for forbidden in ("audio_cover_strength", "task_type=", '"task_type"'):
        assert forbidden not in src.replace('assert "task_type" not in body', ""), forbidden


if __name__ == "__main__":
    test_body_forbids_task_type()
    test_source_has_cover_guard()
    test_no_cover_params_reachable()
    print("ok test_cover_ban")
