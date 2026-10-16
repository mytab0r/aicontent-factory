#!/usr/bin/env python3
"""A/B для владельца (t_d53850f6): 4 сэмпла дня на 4 разных CC BY эталонах -> out/ + report.md.
В прод (public) попадает только одобренное: g1zm0-gate.yml approve=<video_id>.
Запуск: ACE15_ENDPOINT=... G1ZM0_REF_DIR=... python3 g1zm0_ab.py [YYYY-MM-DD] [out_dir] [sec]"""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import g1zm0_rotation as rot  # noqa: E402

spec = importlib.util.spec_from_file_location("music", Path(__file__).parent / "03_music.py")
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)


def main() -> int:
    day = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.datetime.now(dt.timezone.utc).date()
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "out")
    sec = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    out.mkdir(parents=True, exist_ok=True)
    base = music.GENRE_PROMPTS["anime lofi"]
    rows = []
    for i, s in enumerate(rot.ab_samples(day)):
        ref = rot.REF_DIR / f"{s['ref']}.wav"
        assert ref.is_file(), f"нет эталона {ref}: python3 fetch_refs.py"
        f = out / f"ab_{i + 1}_{s['ref']}.mp3"
        prompt = f"{base}, {s['instrument']} melody, {s['key']}, {s['bpm']} BPM"
        music.generate_track_v15(prompt, sec, 1000 + i, f, ref_audio=str(ref), bpm=s["bpm"], key=s["key"])
        rows.append(f"| {i + 1} | {f.name} | {s['ref']} | {s['instrument']} | {s['key']} | {s['bpm']} | {f.stat().st_size} |")
        print("ok", f)
    (out / "report.md").write_text(
        f"# G1zm0 A/B {day}\n\n4 сэмпла, 4 разных эталона (CC BY 3.0, refs/LICENSES.md). "
        "Публикация только после одобрения владельца.\n\n"
        "| # | файл | эталон | инструмент | тональность | BPM | байт |\n|---|---|---|---|---|---|---|\n"
        + "\n".join(rows) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
