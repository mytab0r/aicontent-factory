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
    silent_seeds: set = set()  # кандидат с секундной дырой тишины в середине
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
        assert kw["api_name"] == "/__call__"
        root = 63 if int(kw["manual_seeds"]) in FakeClient.bad_seeds else 57  # D# vs A
        if kw["audio2audio_enable"]:
            assert kw["ref_audio_input"] is not None
        if int(kw["manual_seeds"]) in FakeClient.silent_seeds:
            # кандидат с провалом тишины в середине — pick() должен его отфеть
            sec = kw["audio_duration"]
            x = progression(root, sec)
            n_mid = int(sec * audio_gate.SR) // 2
            hole = np.zeros((audio_gate.SR, 2), np.float32)
            if x.ndim == 1:
                x = np.stack([x, x], 1)
            x = np.concatenate([x[:n_mid], hole, x[n_mid + audio_gate.SR:]], 0)
        else:
            x = progression(root, kw["audio_duration"])
        return [self._wav_arr(x), {}]

    def _wav_arr(self, x):
        FakeClient.n += 1
        p = TMP / f"out{FakeClient.n}.wav"
        audio_gate.write_wav(p, np.stack([x, x], 1) if x.ndim == 1 else x, audio_gate.SR)
        return str(p)


def _split(calls):
    return ([c for c in calls if not c["audio2audio_enable"]],
            [c for c in calls if c["audio2audio_enable"]])


def test_coherent_900s():
    FakeClient.calls, FakeClient.bad_seeds = [], set()
    out = TMP / "track.mp3"
    meta = music.generate_coherent("p", 900, seed=100, out_path=out, client_cls=FakeClient)
    t2m, a2a = _split(FakeClient.calls)
    assert len(t2m) == 1 and t2m[0]["audio_duration"] == music.CHUNK_SEC, t2m
    assert all(c["infer_step"] == music.INFER_STEPS == 60 for c in FakeClient.calls)
    assert a2a and all(c["audio_duration"] <= 240 for c in a2a)
    assert all(c["ref_audio_strength"] == music.A2A_STRENGTH for c in a2a)
    r = audio_gate.check_file(out)
    assert abs(r["duration"] - 900) < 2, r
    assert r["ok"], r
    assert meta["segments"] == 1 + len(a2a), meta


def test_candidate_selection_rejects_wrong_key():
    FakeClient.calls, FakeClient.bad_seeds = [], {101}  # первый кандидат 1-го a2a — мимо
    out = TMP / "track2.mp3"
    meta = music.generate_coherent("p", 400, seed=100, out_path=out, client_cls=FakeClient)
    seeds = [int(c["manual_seeds"]) for c in _split(FakeClient.calls)[1]]
    assert seeds[0] == 101 and seeds[1] != 101, seeds
    assert meta["rejected_candidates"] >= 1, meta
    assert audio_gate.check_file(out)["key_share"] >= 0.85


def test_loudnorm_mp3_hits_target_after_encoding():
    """ТЗ: -14 LUFS, TP <= -1 dBTP с запасом >= 0.1 dB — меряется на итоговом mp3."""
    hot = TMP / "hot.wav"
    x = progression(57, 60)
    x = 0.99 * x / np.abs(x).max()
    audio_gate.write_wav(hot, np.stack([x, x], 1), audio_gate.SR)
    out = TMP / "norm.mp3"
    music.loudnorm_mp3(hot, out)
    r = audio_gate.loudness(out)
    assert abs(r["lufs"] + 14) <= 1.0, r
    assert r["true_peak"] <= -1.1, r


def test_silent_candidate_is_rejected():
    """Кандидат с дырой тишины отбрасывается даже при идеальном строе."""
    FakeClient.calls, FakeClient.bad_seeds = [], set()
    FakeClient.silent_seeds = {101}
    out = TMP / "track3.mp3"
    music.generate_coherent("p", 400, seed=100, out_path=out, client_cls=FakeClient)
    seeds = [int(c["manual_seeds"]) for c in _split(FakeClient.calls)[1]]
    assert seeds[0] == 101 and len(seeds) >= 2, seeds  # дырявый отфильтрован
    assert seeds[1] != 101
    FakeClient.silent_seeds = set()


if __name__ == "__main__":
    test_coherent_900s()
    test_candidate_selection_rejects_wrong_key()
    test_silent_candidate_is_rejected()
    test_loudnorm_mp3_hits_target_after_encoding()
    print("all coherent-music tests passed")
