#!/usr/bin/env python3
"""Self-check t_24f3f36c: g1zm0_rotation.upload_unlisted при uploadLimitExceeded -> None, 1 TG, файл на месте; прочие HttpError падают."""
import json
import sys
import tempfile
import types
from pathlib import Path

from googleapiclient.errors import HttpError, ResumableUploadError

sent = []
sys.modules["common"] = types.SimpleNamespace(tg_send=lambda t: sent.append(t) or True)
sys.path.insert(0, str(Path(__file__).parent))
import g1zm0_rotation as rot  # noqa: E402


def http_error(cls, status, reason):
    body = {"error": {"code": status, "message": "x", "errors": [{"domain": "youtube.video", "reason": reason}]}}
    return cls(types.SimpleNamespace(status=status, reason="Bad Request"), json.dumps(body).encode())


class FakeYT:
    def __init__(self, err): self.err = err
    def videos(self): return self
    def insert(self, **k): return self
    def next_chunk(self, num_retries=0): raise self.err


with tempfile.TemporaryDirectory() as td:
    f = Path(td) / "runs" / "ab_4.mp4"
    f.parent.mkdir()
    f.write_bytes(b"\0" * 1024)
    for cls in (HttpError, ResumableUploadError):
        sent.clear()
        assert rot.upload_unlisted(FakeYT(http_error(cls, 400, "uploadLimitExceeded")), str(f), "t") is None
        assert len(sent) == 1 and "uploadLimitExceeded" in sent[0], sent
        assert f.exists()
    sent.clear()
    other = http_error(HttpError, 403, "quotaExceeded")
    try:
        rot.upload_unlisted(FakeYT(other), str(f), "t")
        raise AssertionError("прочие HttpError должны падать")
    except HttpError as e:
        assert e is other and not sent
print("test_upload_limit_g1zm0 ok")
