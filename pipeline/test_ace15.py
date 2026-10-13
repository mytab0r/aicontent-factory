#!/usr/bin/env python3
"""ACE-Step 1.5 REST: один цельный трек (без склеек), тональность/темп зафиксированы.

Запуск: python3 pipeline/test_ace15.py
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
_spec = importlib.util.spec_from_file_location("music15", Path(__file__).resolve().parent / "03_music.py")
music = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(music)


class FakeApi:
    def __init__(self):
        self.calls = []
        self.polls = 0

    def post(self, path, body):
        self.calls.append((path, body))
        if path == "/release_task":
            return {"data": {"task_id": "t1"}}
        self.polls += 1
        if self.polls < 2:
            return {"data": [{"task_id": "t1", "status": 0}]}
        return {"data": [{"task_id": "t1", "status": 1,
                          "result": json.dumps([{"file": "/v1/audio?path=a.mp3"}, {"file": "/v1/audio?path=b.mp3"}])}]}

    def get(self, path):
        return b"MP3" + path.encode()


def test_single_generation_pinned_key_tempo():
    api = FakeApi()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "t.mp3"
        music.generate_track_v15("lofi piano", 600, 7, out, api=api, poll_sec=0)
        assert out.read_bytes() == b"MP3/v1/audio?path=a.mp3"
    body = api.calls[0][1]
    assert api.calls[0][0] == "/release_task"
    assert body["audio_duration"] == 600
    assert body["key_scale"] and body["bpm"]          # тональность и темп зафиксированы
    assert body["lyrics"] == "[Instrumental]"
    assert body["seed"] == 7 and body["use_random_seed"] is False
    assert body["thinking"] is True                    # LM планирует структуру трека


def test_duration_capped_at_model_limit():
    api = FakeApi()
    with tempfile.TemporaryDirectory() as d:
        music.generate_track_v15("x", 900, 1, Path(d) / "t.mp3", api=api, poll_sec=0)
    assert api.calls[0][1]["audio_duration"] == music.ACE15_MAX_SEC == 600


def test_failed_task_raises():
    class Bad(FakeApi):
        def post(self, path, body):
            if path == "/release_task":
                return {"data": {"task_id": "t1"}}
            return {"data": [{"task_id": "t1", "status": 2, "result": "[]"}]}
    try:
        with tempfile.TemporaryDirectory() as d:
            music.generate_track_v15("x", 60, 1, Path(d) / "t.mp3", api=Bad(), poll_sec=0)
    except RuntimeError:
        return
    raise AssertionError("status=2 must raise")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
