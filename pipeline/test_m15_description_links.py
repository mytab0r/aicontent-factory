#!/usr/bin/env python3
"""M15 (аудит 24.10): описание long-form без ссылки на плейлист и подписку. У лидеров ниши (Lofi Girl, Chillhop)
обе ссылки в первых 2 строках (видны до «ещё»). Регресс: описание выпуска = текст LLM + AI_NOTE + хэштеги, ссылок 0."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("pub", Path(__file__).parent / "05_publish.py")
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)

d = pub.full_description("Cozy rain beats.", ["0:00 A", "8:02 B", "16:04 C"], playlist_id="PLWKVid0L67io")
head = d.splitlines()[:2]
assert any("youtube.com/playlist?list=PLWKVid0L67io" in l for l in head), head
assert any("sub_confirmation=1" in l for l in head), head
assert "Cozy rain beats." in d and "Tracklist" in d and pub.AI_NOTE in d
assert pub.full_description(d, playlist_id="PLWKVid0L67io") == d  # идемпотентно
# без плейлиста подписка всё равно наверху; старый вызов не ломается
assert "sub_confirmation=1" in pub.full_description("x").splitlines()[0]
# body: lofi-выпуск получает ссылки; канал owning — свой формат описания
body = pub.build_body({"title": "Rainy Night Lofi Beats to Study", "description": "Calm."}, {"duration": 3600},
                      playlist_id="PLx")
assert "list=PLx" in body["snippet"]["description"].splitlines()[0], body["snippet"]["description"]
assert len(body["snippet"]["description"]) <= 5000
# оба пути заливки (прямой и claim-гейт daily-video) передают плейлист в описание
assert "release_playlist_id(youtube, idea, meta)" in (Path(__file__).parent / "claim_gate.py").read_text(encoding="utf-8")
class Boom:
    def playlists(self): raise RuntimeError("quota")
assert pub.release_playlist_id(Boom(), {}, {"genre": "anime lofi"}) is None  # сбой API не валит выпуск
assert pub.release_playlist_id(Boom(), {"channel": "owning"}, {"genre": "x"}) is None
print("OK test_m15_description_links")
