"""V11 (аудит 24.10): сезон проверялся только в title (V15). LLM даёт чистый title,
но cover_prompt/description/tags с тыквами в ноябре — обложка «Halloween» после 31.10.
Регресс: 1.11 title без сезона, cover_prompt «pumpkins, halloween candles» = конфликт."""
import importlib.util
from datetime import date
from pathlib import Path

spec = importlib.util.spec_from_file_location("idea", Path(__file__).with_name("01_idea.py"))
idea = importlib.util.module_from_spec(spec)
spec.loader.exec_module(idea)

NOV = date(2026, 11, 1)
bad = {"title": "Rainy Café Window Lofi Beats to Study", "description": "Cozy beats for study.",
       "cover_prompt": "anime café at night, pumpkins and halloween candles on the sill, no text",
       "tags": ["lofi", "halloween lofi", "study music"]}
off = idea.idea_season_conflict(bad, NOV)
assert off == ["halloween"], off  # тыквы в ноябре = поздняя осень, допустимо; Halloween после 31.10 — нет
assert idea.idea_season_conflict(bad, date(2026, 10, 24)) == [], "в октябре тыквы уместны"
clean = dict(bad, cover_prompt="anime café at night, warm tea, falling leaves, no text", tags=["lofi", "study music"])
assert idea.idea_season_conflict(clean, NOV) == [], idea.idea_season_conflict(clean, NOV)
# фолбэк: каждая выбранная сцена согласована с сезоном по всем полям
for m in range(1, 13):
    for i in range(len(idea.SCENES) * len(idea.USES)):
        name, emoji, scene = idea.SCENES[i % len(idea.SCENES)]
        f = {"title": name, "cover_prompt": scene, "description": "", "tags": idea.TAGS}
        if not idea.season_conflict(name, date(2026, m, 1)):
            assert idea.idea_season_conflict(f, date(2026, m, 1)) == [], (m, name, scene)
print("OK test_idea_season_fields")
