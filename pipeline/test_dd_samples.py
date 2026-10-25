#!/usr/bin/env python3
"""Тесты: resume-логика D&D сэмплов (fail-fast + продолжение с места падения).

Покрывает pipeline/dd_samples.py (генератор с чекпоинтами). Принцип:
- каждый успешный трек = сохранённый mp3-артефакт, пропадать не может;
- исчерпание квоты = НЕ ретраи-сон внутри рана, а мгновенный SystemExit
  (не жжём минуты раннера);
- повторный запуск пропускает готовые треки (resume по файлам).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dd_samples


class FakeClient:
    """Эмулирует gradio_client: выдаёт файлы, квота заканчивается после N успехов."""

    def __init__(self, succeed_first: int):
        self.calls = 0
        self.succeed_first = succeed_first

    def predict(self, **kw):
        self.calls += 1
        if self.calls > self.succeed_first:
            raise dd_samples.QuotaExhausted("exceeded your free ZeroGPU quota")
        return self._make_file(kw["prompt"])

    def _make_file(self, prompt):
        p = Path(tempfile.mkdtemp()) / "out.mp3"
        p.write_bytes(b"ID3fake")
        return [str(p)]


def test_quota_is_failfast():
    """Квота -> исключение (workflow падает сразу, не спит 10 часов)."""
    assert issubclass(dd_samples.QuotaExhausted, Exception)


def test_resume_skips_done():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "dd_cozy_tavern.mp3").write_bytes(b"ID3done")
        remaining = dd_samples.pending_scenes(
            dd_samples.SCENES, out
        )
        names = [s["name"] for s in remaining]
        assert "cozy tavern" not in names, "готовый трек не должен генерироваться повторно"
        assert len(names) == len(dd_samples.SCENES) - 1


def test_generate_saves_each_track_and_fails_fast():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        client = FakeClient(succeed_first=2)
        generated, err = dd_samples.run_batch(
            dd_samples.SCENES, out, client_factory=lambda: client
        )
        # первые 2 сгенерились и сохранились ДО падения
        assert generated == 2
        saved = sorted(p.name for p in out.glob("dd_*.mp3"))
        assert len(saved) == 2, f"артефакты пропали: {saved}"
        # ошибка квоты поднята наверх для fail-fast
        assert err is not None and "quota" in str(err).lower()


def test_resume_after_crash_completes():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        # ран 1: упал после 2 треков
        c1 = FakeClient(succeed_first=2)
        dd_samples.run_batch(dd_samples.SCENES, out, client_factory=lambda: c1)
        # ран 2: квота сброшена, всё генерится
        c2 = FakeClient(succeed_first=99)
        generated, err = dd_samples.run_batch(
            dd_samples.SCENES, out, client_factory=lambda: c2
        )
        assert err is None
        saved = list(out.glob("dd_*.mp3"))
        assert len(saved) == len(dd_samples.SCENES)
        assert generated == len(dd_samples.SCENES) - 2, "resume не должен переделывать готовое"


if __name__ == "__main__":
    test_quota_is_failfast()
    test_resume_skips_done()
    test_generate_saves_each_track_and_fails_fast()
    test_resume_after_crash_completes()
    print("all dd_samples tests passed")
