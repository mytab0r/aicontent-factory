#!/usr/bin/env python3
"""Self-check: each genre gets its own playlist, video lands in it (05_publish.py)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("pub", Path(__file__).parent / "05_publish.py")
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)


class Req:
    def __init__(self, r): self.r = r
    def execute(self): return self.r


class FakeYT:
    def __init__(self, existing):
        self.lists = dict(existing)  # title -> id
        self.added = []

    def playlists(self): return self

    def playlistItems(self):
        outer = self
        class PI:
            def insert(self, part, body):
                outer.added.append((body["snippet"]["playlistId"], body["snippet"]["resourceId"]["videoId"]))
                return Req({})
        return PI()

    def list(self, part, mine, maxResults, pageToken=None):
        return Req({"items": [{"id": i, "snippet": {"title": t}} for t, i in self.lists.items()]})

    def insert(self, part, body):
        t = body["snippet"]["title"]
        self.lists[t] = f"PL{len(self.lists)}"
        return Req({"id": self.lists[t]})


yt = FakeYT({"Anime Lofi Beats": "PLa"})
assert pub.playlist_title("anime lofi") == "Anime Lofi Beats"
assert pub.add_to_genre_playlist(yt, "v1", "anime lofi") == "PLa"          # existing reused
pid = pub.add_to_genre_playlist(yt, "v2", "jazzhop")                       # new created once
assert pub.add_to_genre_playlist(yt, "v3", "jazzhop") == pid
assert yt.added == [("PLa", "v1"), (pid, "v2"), (pid, "v3")], yt.added
assert len(yt.lists) == 2
d = pub.full_description("Chill beats.")
assert "#lofi #animelofi #studymusic" in d and "AI-generated" in d, d
assert pub.full_description(d) == d  # идемпотентно
print("OK test_playlist")
