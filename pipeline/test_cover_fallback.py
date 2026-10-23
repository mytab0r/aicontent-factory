#!/usr/bin/env python3
"""V14 (каталог): при сбое image API 02_cover ставит градиент-заглушку без арта; YAVG градиента 40-90 проходит V9,
поэтому выпуск уходил с пустой картинкой. Теперь 02 пишет маркер cover_fallback.json, 04b (--final) = FAIL."""
import importlib.util, json, sys, tempfile, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import quality_gate as qg

with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    (d / "idea.json").write_text(json.dumps({"cover_prompt": "Night Train window"}), encoding="utf-8")

    def down(*a, **k):
        raise RuntimeError("503 image API down")
    sys.modules["common"] = types.SimpleNamespace(router_post=down, latest_run_dir=lambda: d)
    spec = importlib.util.spec_from_file_location("cover", Path(__file__).parent / "02_cover.py")
    cover = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cover)
    assert qg.fallback_why(d) == []  # чистый прогон без маркера = ok
    cover.main()
    assert (d / "cover.png").exists()
    assert (d / "cover_fallback.json").exists(), "02_cover не пометил заглушку"
    why = qg.fallback_why(d)
    assert why and "заглушка" in why[0], why
print("test_cover_fallback OK")
