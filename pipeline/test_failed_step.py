#!/usr/bin/env python3
"""t_fe1fcf66: TG-алерт называет упавший шаг. API jobs в момент алерта ещё без conclusion
(run 39115022028 -> «не определён»), поэтому источник — контекст steps текущей джобы."""
from pathlib import Path
from common import failed_step

WF = (Path(__file__).parent.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")
steps = {"guard": {"outcome": "success", "conclusion": "success"},
         "music": {"outcome": "failure", "conclusion": "failure"},
         "ref": {"outcome": "failure", "conclusion": "success"}}  # continue-on-error не считается
assert failed_step(steps, [], WF) == "03 music (ACE-Step)", failed_step(steps, [], WF)
# API догнал — тоже годится; пусто везде — честное «не определён»
jobs = [{"steps": [{"name": "05 publish", "conclusion": "failure"}]}]
assert failed_step({}, jobs, WF) == "05 publish"
assert failed_step({}, [{"steps": [{"name": "x", "conclusion": None}]}], WF) == "не определён"
# каждый шаг, который может упасть, имеет id (иначе в steps-контексте его нет)
import re
for name in re.findall(r"- name: (0\d\w? [^\n]+)", WF):
    assert re.search(rf"- name: {re.escape(name)}\n\s+id: ", WF), f"нет id у шага: {name}"
print("OK test_failed_step")
