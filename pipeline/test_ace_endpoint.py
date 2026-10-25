#!/usr/bin/env python3
"""Тесты: выбор endpoint для ACE-Step (локальный GPU-ПК через туннель vs HF Space).

Запуск: python3 pipeline/test_ace_endpoint.py
Покрывает 03_music.ace_endpoint(): ACE_ENDPOINT env -> локальный URL
(без токена, Tailscale-туннель к GPU-ПК владельца), иначе HF Space
с HF_TOKEN. Локальный ACE-Step = тот же Gradio-интерфейс, те же
параметры — gradio_client совместим без изменений пайплайна.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "music_mod", Path(__file__).resolve().parent / "03_music.py"
)
music = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(music)


class FakeClient:
    calls = {}

    def __init__(self, src, token=None):
        FakeClient.calls = {"src": src, "token": token}

    def predict(self, **kw):
        FakeClient.calls["kw"] = kw
        return ["/tmp/fake.mp3"]


def test_local_endpoint_used_when_set():
    os.environ["ACE_ENDPOINT"] = "http://100.64.0.5:7860"
    url, token = music.ace_endpoint()
    assert url == "http://100.64.0.5:7860", url
    assert token is None, token  # локальный — без HF токена


def test_space_fallback_without_env():
    os.environ.pop("ACE_ENDPOINT", None)
    os.environ.pop("HF_TOKEN", None)
    url, token = music.ace_endpoint()
    assert url == music.SPACE
    assert token is None


def test_space_fallback_with_token():
    os.environ.pop("ACE_ENDPOINT", None)
    os.environ["HF_TOKEN"] = "hf_test"
    url, token = music.ace_endpoint()
    assert url == music.SPACE
    assert token == "hf_test"
    os.environ.pop("HF_TOKEN", None)


def test_generate_track_routes_to_local():
    os.environ["ACE_ENDPOINT"] = "http://100.64.0.5:7860"
    out = music.generate_track("test prompt", 45, seed=7, client_cls=FakeClient)
    assert out == "/tmp/fake.mp3"
    c = FakeClient.calls
    assert c["src"] == "http://100.64.0.5:7860"
    assert c["token"] is None
    assert c["kw"]["audio_duration"] == 45.0
    assert c["kw"]["prompt"] == "test prompt"
    assert c["kw"]["manual_seeds"] == "7"
    os.environ.pop("ACE_ENDPOINT", None)


if __name__ == "__main__":
    test_local_endpoint_used_when_set()
    test_space_fallback_without_env()
    test_space_fallback_with_token()
    test_generate_track_routes_to_local()
    print("all ace_endpoint tests passed")
