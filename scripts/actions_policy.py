#!/usr/bin/env python3
"""t_d2da98e8: allowlist экшенов репо = единственный источник правды для политики GitHub Actions.

Почему: квота artifact storage Free = ГБ-часы на весь аккаунт. Линт (ci_bypass_lint) видит только
master/PR, а workflow запускается С ТОЙ ВЕТКИ, где лежит (push/workflow_dispatch). 39879816809
(ветка t_f807dc99, retention-days: 14) и 39897824919 (wt/t_2ca44c81-flint, без retention) упали
'Artifact storage quota has been hit' с веток, которых линт не касался (89 из 144 веток).
Политика репо `allowed_actions: selected` с этим списком рубит upload/download-artifact на ЛЮБОЙ ветке
до старта job; этот скрипт держит список и workflows master в согласии.

usage: actions_policy.py [ROOT]     — FAIL, если workflow использует экшен вне ALLOW (CI, ci-bypass-lint)
       actions_policy.py --apply R  — выставить политику репо R (gh api, нужен admin-токен)
       actions_policy.py --check R  — FAIL при дрейфе живой политики R от ALLOW
"""
import json
import pathlib
import re
import subprocess
import sys

# upload-artifact/download-artifact сюда не добавлять: медиа идут через deploy/gpu-pc/acf_out.sh (t_265d0147)
ALLOW = sorted([
    "actions/checkout@*",
    "actions/setup-node@*",
    "actions/setup-python@*",
    "astral-sh/setup-uv@*",
    "docker/setup-buildx-action@*",
    "docker/build-push-action@*",
    "docker/metadata-action@*",
])
USES = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^\s'\"#@]+)@")


def allowed(action):
    return action.startswith("./") or any(action == p.split("@")[0] for p in ALLOW)


def lint(root="."):
    bad = []
    for f in sorted(pathlib.Path(root, ".github/workflows").glob("*.y*ml")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = USES.match(line)
            if m and not allowed(m.group(1)):
                bad.append(f"{f.as_posix()}:{n}: action-not-allowed: {m.group(1)}")
    return bad


def gh(*a, data=None):
    return subprocess.run(["gh", "api", *a], input=data, capture_output=True, text=True, check=True).stdout


def policy(repo):
    p = json.loads(gh(f"repos/{repo}/actions/permissions"))
    if p.get("allowed_actions") != "selected":
        return p.get("allowed_actions"), None
    return "selected", json.loads(gh(f"repos/{repo}/actions/permissions/selected-actions"))


def drift(mode, sel):
    if mode != "selected":
        return [f"allowed_actions={mode}, нужно selected"]
    out = []
    if sel.get("github_owned_allowed") or sel.get("verified_allowed"):
        out.append("github_owned_allowed/verified_allowed должны быть false (иначе upload-artifact снова разрешён)")
    if sorted(sel.get("patterns_allowed", [])) != ALLOW:
        out.append(f"patterns_allowed={sorted(sel.get('patterns_allowed', []))} != {ALLOW}")
    return out


def apply(repo):
    gh("-X", "PUT", f"repos/{repo}/actions/permissions", "--input", "-",
       data=json.dumps({"enabled": True, "allowed_actions": "selected"}))
    gh("-X", "PUT", f"repos/{repo}/actions/permissions/selected-actions", "--input", "-",
       data=json.dumps({"github_owned_allowed": False, "verified_allowed": False, "patterns_allowed": ALLOW}))


def _selftest():
    assert allowed("actions/checkout") and allowed("./.github/actions/x")
    assert not allowed("actions/upload-artifact") and not allowed("actions/download-artifact")
    assert drift("all", None) and drift("selected", {"github_owned_allowed": True, "patterns_allowed": ALLOW})
    assert drift("selected", {"patterns_allowed": ALLOW + ["actions/upload-artifact@*"]})
    assert drift("selected", {"github_owned_allowed": False, "verified_allowed": False, "patterns_allowed": ALLOW}) == []
    assert USES.match("      - uses: actions/upload-artifact@v4  # x").group(1) == "actions/upload-artifact"


if __name__ == "__main__":
    _selftest()
    if sys.argv[1:2] == ["--apply"]:
        apply(sys.argv[2])
    if sys.argv[1:2] in (["--apply"], ["--check"]):
        d = drift(*policy(sys.argv[2]))
        print("\n".join(d) or f"ok: policy {sys.argv[2]}")
        sys.exit(1 if d else 0)
    b = lint(*sys.argv[1:2])
    print("\n".join(b) or "ok: actions allowlist")
    sys.exit(1 if b else 0)
