#!/usr/bin/env python3
"""Self-check t_24f3f36c: uploadLimitExceeded = пропуск слота (1 TG, без падения, видео в runs/); прочие HttpError падают."""
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

from googleapiclient.errors import HttpError, ResumableUploadError

sent = []
sys.modules["common"] = types.SimpleNamespace(latest_run_dir=None, tg_send=lambda t: sent.append(t) or True)
sys.modules.setdefault("youtube_oauth", types.SimpleNamespace(TOKEN_PATH=None, check_auth=None))
spec = importlib.util.spec_from_file_location("pub", Path(__file__).parent / "05_publish.py")
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)


def http_error(cls, status, reason):
    resp = types.SimpleNamespace(status=status, reason="Bad Request")
    body = {"error": {"code": status, "message": "x", "errors": [{"domain": "youtube.video", "reason": reason}]}}
    return cls(resp, json.dumps(body).encode())


class FakeYT:
    def __init__(self, err): self.err = err
    def videos(self): return self
    def insert(self, **k): return self
    def next_chunk(self, num_retries=0): raise self.err


def run(err):
    sent.clear()
    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td) / "runs" / "20261016_090000"
        run_dir.mkdir(parents=True)
        (run_dir / "idea.json").write_text(json.dumps({"title": "t", "description": "d"}))
        (run_dir / "video.mp4").write_bytes(b"\0" * 1024)
        pub._get_youtube_service = lambda: FakeYT(err)
        try:
            return pub.publish(run_dir), None
        except Exception as e:
            return None, e
        finally:
            assert (run_dir / "video.mp4").exists(), "видео должно остаться в runs/"
            assert not (run_dir / "published.json").exists()


for cls in (HttpError, ResumableUploadError):  # реальный next_chunk бросает ResumableUploadError
    url, exc = run(http_error(cls, 400, "uploadLimitExceeded"))
    assert exc is None and url is None, exc
    assert len(sent) == 1 and "uploadLimitExceeded" in sent[0], sent

other = http_error(HttpError, 403, "quotaExceeded")
url, exc = run(other)
assert exc is other and not sent, (exc, sent)
print("test_upload_limit ok")
