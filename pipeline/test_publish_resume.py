#!/usr/bin/env python3
"""Self-check: обрыв чанка (TimeoutError) не валит выпуск, upload продолжается через status-запрос (05_publish.py)."""
import importlib.util
import sys
import types
from pathlib import Path

for m in ("common", "youtube_oauth"):
    sys.modules.setdefault(m, types.SimpleNamespace(latest_run_dir=None, TOKEN_PATH=None, check_auth=None))
spec = importlib.util.spec_from_file_location("pub", Path(__file__).parent / "05_publish.py")
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)


class Req:
    def __init__(self, fails):
        self.fails, self.calls, self.error_states = fails, 0, []

    def next_chunk(self, num_retries=0):
        self.calls += 1
        self.error_states.append(getattr(self, "_in_error_state", False))
        if self.fails:
            self.fails -= 1
            raise TimeoutError("The read operation timed out")
        return None, {"id": "vid1"}


r = Req(fails=3)
assert pub.upload_resumable(r, sleep=lambda s: None) == {"id": "vid1"}
assert r.calls == 4 and r.error_states[-1] is True  # после ошибки — status-запрос, не повтор вслепую

r = Req(fails=99)
try:
    pub.upload_resumable(r, max_errors=3, sleep=lambda s: None)
    raise AssertionError("должен упасть после max_errors")
except TimeoutError:
    pass
assert r.calls == 4
try:
    import googleapiclient  # noqa: F401  (есть в CI/на раннере)
except ImportError:
    print("skip upload_http: нет googleapiclient")
else:
    h = pub.upload_http()
    assert 308 not in h.redirect_codes, "308 = resumable 'продолжай', не редирект"
    assert h.timeout == 300
print("test_publish_resume ok")
