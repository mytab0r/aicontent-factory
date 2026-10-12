#!/usr/bin/env python3
"""Тест связной генерации long-form трека (kanban t_44de72aa).

Было: 4 независимых text2music-куска с разными seed -> 3 тональности,
дрейф строя, -56 dB дыры на стыках. Стало: первый кусок text2music, дальше
ACE-Step extend (продолжение хвоста предыдущего аудио), N кандидатов на
кусок с выбором по совпадению тональности/строя, equal-power crossfade,
loudnorm -14 LUFS / TP <= -1. Проверяем на фейковом клиенте (без GPU).
Запуск: python3 pipeline/test_music_coherent.py (нужны numpy + ffmpeg).
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audio_gate  # noqa: E402
from test_audio_gate import progression  # noqa: E402

spec = importlib.util.spec_from_file_location("music", HERE / "03_music.py")
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)

TMP = Path(tempfile.mkdtemp())


class FakeClient:
    calls: list = []
    bad_seeds: set = set()  # extend с этими seed уходит в другую тональность
    n = 0

    def __init__(self, src, token=None):
        pass

    def _wav(self, sec, root, cents=0.0):
        FakeClient.n += 1
        p = TMP / f"out{FakeClient.n}.wav"
        x = progression(root, sec, cents)
        # SR гейта 22050 — фейку хватает, 03_music ресемплит сам
        audio_gate.write_wav(p, np.stack([x, x], 1), audio_gate.SR)
        return str(p)

    def predict(self, **kw):
        FakeClient.calls.append(kw)
        if kw["api_name"] == "/__call__":
            return [self._wav(kw["audio_duration"], 57), {}]  # A
        assert kw["api_name"] == "/extend_process_func"
        src = kw["extend_source_audio_upload"]
        src = src["path"] if isinstance(src, dict) else src
        tail = len(audio_gate.decode(src)) / audio_gate.SR
        seed = int(kw["extend_seeds"])
        root = 63 if seed in FakeClient.bad_seeds else 57  # D# vs A
        return [self._wav(tail + kw["right_extend_length"], root), {}]


def test_coherent_900s():
    FakeClient.calls, FakeClient.bad_seeds = [], set()
    out = TMP / "track.mp3"
    meta = music.generate_coherent("p", 900, seed=100, out_path=out, client_cls=FakeClient)
    t2m = [c for c in FakeClient.calls if c["api_name"] == "/__call__"]
    ext = [c for c in FakeClient.calls if c["api_name"] == "/extend_process_func"]
    assert len(t2m) == 1 and t2m[0]["audio_duration"] == music.FIRST_SEC, t2m
    assert all(c["infer_step"] == music.INFER_STEPS == 60 for c in FakeClient.calls)
    assert ext and all(c["extend_source"] == "upload" and c["right_extend_length"] <= 240 for c in ext)
    r = audio_gate.check_file(out)
    assert abs(r["duration"] - 900) < 2, r
    assert r["ok"], r
    assert abs(r["lufs"] + 14) < 1.0, r
    assert meta["segments"] == 1 + len(ext), meta


def test_candidate_selection_rejects_wrong_key():
    FakeClient.calls, FakeClient.bad_seeds = [], {101}  # первый кандидат 1-го extend — мимо
    out = TMP / "track2.mp3"
    meta = music.generate_coherent("p", 400, seed=100, out_path=out, client_cls=FakeClient)
    ext_seeds = [int(c["extend_seeds"]) for c in FakeClient.calls if c["api_name"] == "/extend_process_func"]
    assert ext_seeds[0] == 101 and ext_seeds[1] != 101, ext_seeds
    assert meta["rejected_candidates"] >= 1, meta
    assert audio_gate.check_file(out)["key_share"] >= 0.85


if __name__ == "__main__":
    test_coherent_900s()
    test_candidate_selection_rejects_wrong_key()
    print("all coherent-music tests passed")
