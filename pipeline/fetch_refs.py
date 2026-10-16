#!/usr/bin/env python3
"""Скачивает пул эталонов (CC BY, Wikimedia Commons) и режет по 90 с в refs/<slug>.wav.
WAV в git не коммитим (~15 МБ каждый) — запуск: python3 pipeline/fetch_refs.py. Лицензии: refs/LICENSES.md."""
import hashlib, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import g1zm0_rotation as rot

UA = {"User-Agent": "aicontent-factory/1.0 (refs fetch)"}

def main() -> int:
    rot.REF_DIR.mkdir(parents=True, exist_ok=True)
    for slug, (title, start) in rot.REF_SOURCES.items():
        out = rot.REF_DIR / f"{slug}.wav"
        if out.exists():
            continue
        name = title.removeprefix("File:").replace(" ", "_")
        h = hashlib.md5(name.encode()).hexdigest()  # прямой путь upload.* (Special:FilePath режется 429)
        url = f"https://upload.wikimedia.org/wikipedia/commons/{h[0]}/{h[:2]}/{urllib.parse.quote(name)}"
        src = out.with_suffix(".src")
        for a in range(6):  # Commons отдаёт 429 при частых запросах
            try:
                src.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read())
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or a == 5:
                    raise
                time.sleep(60 * (a + 1))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(rot.REF_SECONDS), "-i", str(src),
                        "-ar", "44100", "-ac", "2", str(out)], check=True)
        src.unlink()
        print("ok", slug)
        time.sleep(5)  # вежливость к Commons
    return 0

if __name__ == "__main__":
    sys.exit(main())
