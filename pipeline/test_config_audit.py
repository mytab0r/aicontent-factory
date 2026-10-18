#!/usr/bin/env python3
"""Самопроверка config_audit (t_bb361290): текущие настройки согласованы; подставленная
рассогласованная конфигурация (жанр без цепочки / эталона / порога / с кривыми полосами) даёт FAIL."""
import importlib.util
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_audit import audit_config

import mastering
import quality_gate as qg

CH = {"lofi": "highpass,loudnorm", "phonk": "acompressor"}
REF_OK = {"lofi": {"bands": [0.0] * 8, "min_lra": 5.0},
          "phonk": {"bands": [0.0] * 8, "min_lra": 0.0}}

# 1) согласованная конфигурация проходит
assert audit_config(["anime lofi", "chill phonk"], REF_OK, 8, CH) == []
# 2) реальные quality_gate/mastering/03_music согласованы между собой
spec = importlib.util.spec_from_file_location("music03", Path(__file__).parent / "03_music.py")
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)
real_chains = {"lofi": mastering.LOFI_AF,
               "phonk": inspect.getsource(mastering.master)}
assert audit_config(music.GENRE_PROMPTS.keys(), qg.REF, len(qg.BANDS), real_chains) == []
# 3) жанр без эталон-профиля -> FAIL, в сообщении жанр и ключ
issues = audit_config(["jazzhop"], {"phonk": REF_OK["phonk"]}, 8, CH)
assert any("jazzhop" in x and "REF['lofi']" in x for x in issues), issues
# 4) жанр без порога LRA -> FAIL
issues = audit_config(["anime lofi"], {"lofi": {"bands": [0.0] * 8}}, 8, CH)
assert any("min_lra" in x and "anime lofi" in x for x in issues), issues
# 5) эталон с чужим числом полос -> FAIL
issues = audit_config(["anime lofi"], {"lofi": {"bands": [0.0] * 5, "min_lra": 5.0}}, 8, CH)
assert any("5 полос, гейт меряет 8" in x for x in issues), issues
# 6) жанр без мастеринг-цепочки -> FAIL
issues = audit_config(["chill phonk"], REF_OK, 8, {"lofi": "highpass"})
assert any("chill phonk" in x and "цепочки" in x for x in issues), issues
# 7) байт-в-байт: сломали REF в реальном модуле -> аудит на реальных модулях ловит
saved = qg.REF.pop("lofi")
issues = audit_config(music.GENRE_PROMPTS.keys(), qg.REF, len(qg.BANDS), real_chains)
qg.REF["lofi"] = saved
assert any("REF['lofi']" in x for x in issues), issues

print("test_config_audit OK")
