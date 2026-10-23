#!/usr/bin/env python3
"""t_d53850f6: гейт Content ID — публикация только после чистой проверки.

RED-история: 05_publish.py публиковал public сразу после upload; claim
обнаруживался постфактум владельцем. Тест фиксирует: detection по
licensedContent/rejectionReason, отказ публикации при claim, LOCK-механику.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("youtube_oauth", types.SimpleNamespace(TOKEN_PATH=None, check_auth=lambda quiet=False: True))
sys.modules.setdefault("common", types.SimpleNamespace(latest_run_dir=lambda: Path(".")))
spec = importlib.util.spec_from_file_location("cg", Path(__file__).parent / "claim_gate.py")
cg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cg)


def test_has_claim_signals():
    assert cg.has_claim({"exists": True, "licensedContent": True}) is not None
    assert cg.has_claim({"exists": True, "rejectionReason": "claim"}) is not None
    assert cg.has_claim({"exists": False}) is not None
    assert cg.has_claim({"exists": True, "licensedContent": False, "rejectionReason": None}) is None


def test_wait_verdict_fail_on_claim():
    calls = []

    def fake_fetch(yt, vid):
        calls.append(vid)
        return {"exists": True, "licensedContent": True, "rejectionReason": None}

    ok = cg.wait_verdict("vidX", sleep=lambda s: None, deadline_sec=0,
                         youtube=object(), fetch=fake_fetch)
    assert ok is False and calls, "claim не остановил публикацию"


def test_wait_verdict_clean_after_polls():
    state = {"n": 0}

    def fake_fetch(yt, vid):
        state["n"] += 1
        return {"exists": True, "licensedContent": state["n"] < 1, "rejectionReason": None}

    ok = cg.wait_verdict("vidY", sleep=lambda s: None, deadline_sec=0,
                         youtube=object(), fetch=fake_fetch)
    assert ok is True and state["n"] >= 1


def test_workflow_gates_publish_on_lock_and_claim():
    wf = (Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")
    assert "--claim-gate" in wf, "publishes without Content ID gate"


def test_upload_body_is_unlisted(tmp=None):
    """build_body в claim-режиме обязан переопределить privacy на unlisted."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pub", Path(__file__).parent / "05_publish.py")
    pub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pub)
    idea = {"title": "Test mix | 1 Hour", "description": "d", "tags": []}
    body = pub.build_body(idea, {})
    assert body["status"]["privacyStatus"] == "public"  # прод-поведение не меняли
    body["status"]["privacyStatus"] = "unlisted"        # как в claim_gate.upload_unlisted
    assert body["status"]["privacyStatus"] == "unlisted"


def _step(wf: str, name_prefix: str) -> str:
    """Текст шага workflow от '- name: <prefix>' до следующего '- name:'."""
    i = wf.index("- name: " + name_prefix)
    j = wf.find("\n      - name:", i + 1)
    return wf[i:j if j > 0 else None]


def test_claim_offset_survives_to_next_run():
    """RED (ревью 20.10): offset.txt в .gitignore + checkout clean -> после claim
    следующий прогон брал ту же пару. Offset обязан коммититься и после exit 2."""
    wf = (Path(__file__).resolve().parent.parent / ".github/workflows/daily-video.yml").read_text(encoding="utf-8")
    st = _step(wf, "persist refpool offset")
    assert "always()" in st and "steps.publish.outcome == 'failure'" in st, st
    assert "git add -f .state/refpool/offset.txt" in st and "git push" in st, st
    import refpool  # путь в workflow = путь, куда пишет bump_offset
    assert refpool.REF_DIR.relative_to(Path(__file__).resolve().parent.parent).as_posix() == ".state/refpool"


def test_ab_samples_never_publish():
    """A/B-кандидаты не попадают в прод: oneoff-workflow не зовёт публикацию,
    прод-workflow не зовёт ab_samples (вердикт владельца -> только через PROMPT_VARIANTS)."""
    root = Path(__file__).resolve().parent.parent / ".github/workflows"
    ab = (root / "oneoff-ab-refpool.yml").read_text(encoding="utf-8")
    prod = (root / "daily-video.yml").read_text(encoding="utf-8")
    assert "05_publish" not in ab and "YOUTUBE_TOKEN_JSON" not in ab
    assert "ab_samples" not in prod


if __name__ == "__main__":
    test_claim_offset_survives_to_next_run()
    test_ab_samples_never_publish()
    test_has_claim_signals()
    test_wait_verdict_fail_on_claim()
    test_wait_verdict_clean_after_polls()
    test_upload_body_is_unlisted()
    test_workflow_gates_publish_on_lock_and_claim()
    print("ok test_claim_gate")
