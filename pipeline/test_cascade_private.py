#!/usr/bin/env python3
"""M13/M10: public-шортс со ссылкой Full mix на скрытый long-form обязан уйти в private (каскад)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import cascade_private as cp

# 17.10: long-form p-kkEmLGviU скрыт аудитом, шортсы dH76zOaDm8o/NM04LtSL_4Y вели на него (скрывались вручную).
V = [{"id": "p-kkEmLGviU", "privacy": "private", "description": "mix"},
     {"id": "dH76zOaDm8o", "privacy": "public", "description": "Full mix: https://www.youtube.com/watch?v=p-kkEmLGviU\n\nAI"},
     {"id": "NM04LtSL_4Y", "privacy": "public", "description": "Full mix: https://youtu.be/p-kkEmLGviU"},
     {"id": "AAAAAAAAAAA", "privacy": "public", "description": "long ok"},
     {"id": "BBBBBBBBBBB", "privacy": "public", "description": "Full mix: https://www.youtube.com/watch?v=AAAAAAAAAAA"},
     {"id": "CCCCCCCCCCC", "privacy": "public", "description": "Full mix: https://www.youtube.com/watch?v=ZZZZZZZZZZZ"},
     {"id": "DDDDDDDDDDD", "privacy": "private", "description": "Full mix: https://www.youtube.com/watch?v=p-kkEmLGviU"}]
got = cp.orphans(V)
assert ("dH76zOaDm8o", "p-kkEmLGviU") in got and ("NM04LtSL_4Y", "p-kkEmLGviU") in got, got
assert ("CCCCCCCCCCC", "ZZZZZZZZZZZ") in got, got          # long удалён = тоже недоступен
assert all(s not in ("BBBBBBBBBBB", "DDDDDDDDDDD", "AAAAAAAAAAA") for s, _ in got), got  # живой long / уже private
assert len(got) == 3, got
# M18 (аудит 24.10): «Chill Phonk Beats» public, 0 public из 2; «Anime Lofi Beats» 1 из 8; «Интересное» unlisted.
PL = [{"id": "PLQZ7XaUfORfk", "privacy": "public", "items": ["private", "private"]},
      {"id": "PLWKVid0L67io", "privacy": "public", "items": ["public"] + ["private"] * 7},
      {"id": "PLempty", "privacy": "public", "items": []},
      {"id": "PL0eYy9MeE3", "privacy": "unlisted", "items": ["private"]}]
assert cp.empty_playlists(PL) == ["PLQZ7XaUfORfk", "PLempty"], cp.empty_playlists(PL)
print("OK test_cascade_private")
