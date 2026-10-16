#!/usr/bin/env python3
"""t_841ee449: A/B не назначается на день выпуска; uploadLimitExceeded = transient (None, не исключение)."""
import datetime as dt
import json
import sys
import types
from pathlib import Path

from googleapiclient.errors import HttpError

sys.modules["common"] = types.SimpleNamespace(tg_send=lambda t: True)
sys.path.insert(0, str(Path(__file__).parent))
import g1zm0_rotation as rot  # noqa: E402

fri = dt.date(2026, 10, 16)  # пятница, weekday=4
assert fri.weekday() == 4
# выпуски пн-пт -> A/B переносится на субботу
assert rot.ab_upload_day(fri, {0, 1, 2, 3, 4}) == dt.date(2026, 10, 17)
# сегодня свободен -> сегодня
assert rot.ab_upload_day(fri, {0, 1, 2, 3}) == fri
# выпуск каждый день -> свободного дня нет, A/B не назначается
assert rot.ab_upload_day(fri, range(7)) is None
# никогда не попадает на день выпуска
for wd in range(7):
    rel = set(range(7)) - {wd}
    for i in range(14):
        d = rot.ab_upload_day(fri + dt.timedelta(i), rel)
        assert d is not None and d.weekday() not in rel


class FakeYT:
    def videos(self): return self
    def insert(self, **k): return self
    def next_chunk(self, num_retries=0):
        body = {"error": {"code": 400, "errors": [{"reason": "uploadLimitExceeded"}]}}
        raise HttpError(types.SimpleNamespace(status=400, reason="Bad Request"), json.dumps(body).encode())


f = Path(__file__)  # любой существующий файл
rot.RELEASE_WEEKDAYS = {0, 1, 2, 3, 4}
sat = dt.date(2026, 10, 17)
assert rot.upload_unlisted(FakeYT(), str(f), "t", today=sat) is None  # uploadLimitExceeded: transient, retry позже, не fail


class Boom(FakeYT):
    def insert(self, **k): raise AssertionError("в день выпуска A/B не грузится")


assert rot.upload_unlisted(Boom(), str(f), "t", today=fri) is None  # пятница = выпуск -> отложено
print("test_ab_release_days ok")
