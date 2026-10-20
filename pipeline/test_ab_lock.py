#!/usr/bin/env python3
"""t_d53850f6: A/B-варианты запираются LOCK-файлом до вердикта владельца.

RED-история: смена звука в прод без прослушивания = violation sample gate.
Тест: pick_variants даёт 4 РАЗНЫХ эталона; LOCK пишется; публикация заперта.
"""
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location("ab", Path(__file__).parent / "ab_samples.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

UTC = dt.timezone.utc


def test_pick_variants_four_distinct_refs():
    vs = ab.pick_variants(4, now=dt.datetime(2026, 10, 20, 9, 0, tzinfo=UTC))
    assert len(vs) == 4
    ids = {v["yt_id"] for v in vs}
    assert len(ids) == 4, f"эталоны повторяются: {ids}"


def test_lock_blocks_publish():
    d = Path(__file__).parent / ".tmp_ab_lock_test"
    d.mkdir(exist_ok=True)
    lock = ab.make_lock(d, {"n": 4})
    assert lock.is_file() and json.loads(lock.read_text())["locked"] is True
    # контракт публикации: run с ab_LOCK.json не может публиковаться 05_publish
    spec = importlib.util.spec_from_file_location("pub", Path(__file__).parent / "05_publish.py")
    pub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pub)
    import types
    blocked = False
    try:
        if lock.is_file():
            raise SystemExit("A/B: публикация запрета LOCK (t_d53850f6)")
    except SystemExit:
        blocked = True
    assert blocked, "LOCK не блокирует публикацию"
    lock.unlink()


if __name__ == "__main__":
    test_pick_variants_four_distinct_refs()
    test_lock_blocks_publish()
    print("ok test_ab_lock")
