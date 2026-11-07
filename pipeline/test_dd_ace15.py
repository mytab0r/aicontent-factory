#!/usr/bin/env python3
"""Тесты: отказ dd_samples от ZeroGPU (root-cause t_61f7c556).

AC: когда ACE15_ENDPOINT задан — треки идут на локальный REST, gradio_client
не вызывается; без endpoint — Fast fail с внятной ошибкой.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dd_samples


def test_without_endpoint_fast_fail_no_calls():
    """ACE15_ENDPOINT не задан -> таблица ошибок, генератор не зовётся."""
    saved = os.environ.pop("ACE15_ENDPOINT", None)
    try:
        calls = []
        with tempfile.TemporaryDirectory() as td:
            generated, err = dd_samples.run_local_generation(
                dd_samples.SCENES, Path(td), generate=lambda *a, **kw: calls.append(a)
            )
        assert generated == 0, generated
        assert err is not None and "ACE15_ENDPOINT" in str(err), err
        assert calls == [], calls
    finally:
        if saved is not None:
            os.environ["ACE15_ENDPOINT"] = saved


def test_with_endpoint_local_generation_no_quota():
    """ACE15_ENDPOINT задан -> generate_track_v15 по каждой сцене, файлы сохранены."""
    os.environ["ACE15_ENDPOINT"] = "http://ace-step:8001"
    calls = []

    def fake_generate(prompt, duration, seed, out_path, api=None):
        calls.append(prompt)
        Path(out_path).write_bytes(b"ID3fake")

    with tempfile.TemporaryDirectory() as td:
        generated, err = dd_samples.run_local_generation(
            dd_samples.SCENES, Path(td), generate=fake_generate
        )
        assert err is None, err
        saved = sorted(p.name for p in Path(td).glob("dd_*.mp3"))
        assert len(saved) == len(dd_samples.SCENES) == generated
    assert len(calls) == len(dd_samples.SCENES)


def test_resume_skips_done_locally():
    os.environ["ACE15_ENDPOINT"] = "http://ace-step:8001"
    with tempfile.TemporaryDirectory() as td:
        first = dd_samples.SCENES[0]["name"].replace(" ", "_")
        (Path(td) / f"dd_{first}.mp3").write_bytes(b"ID3done")
        calls = []

        def fake_generate(prompt, duration, seed, out_path, api=None):
            calls.append(prompt)
            Path(out_path).write_bytes(b"ID3fake")

        generated, err = dd_samples.run_local_generation(
            dd_samples.SCENES, Path(td), generate=fake_generate
        )
        assert err is None and generated == len(dd_samples.SCENES) - 1
        assert len(calls) == len(dd_samples.SCENES) - 1


if __name__ == "__main__":
    test_without_endpoint_fast_fail_no_calls()
    test_with_endpoint_local_generation_no_quota()
    test_resume_skips_done_locally()
    print("dd ace15 tests passed")
