#!/usr/bin/env python3
"""CI-линт обходов гейтов («Повтор = класс», ai-dev-engineering #25).
FAIL на: docker/login-action и `docker login` (daemon /auth, t_0deb6ad8) | setup-buildx-action без `driver: docker` (t_a41372f5) | continue-on-error: true | `|| true`/`|| :` после теста/гейта/upload/push | actions/upload-artifact.
Разрешение: `# root-cause: t_<id>` (первые два) или `# artifact-ok: <причина>` (upload) в той же строке
или в непрерывном блоке комментариев прямо над строкой.
Usage: python3 ci_bypass_lint.py [ROOT]"""
import pathlib
import re
import sys

COE = re.compile(r"""^\s*-?\s*continue-on-error:\s*['"]?true['"]?\s*(#.*)?$""", re.I)
OR_TRUE = re.compile(r"\|\|\s*(?:true|:)(?=$|[\s;)#])")
GATE = re.compile(r"\b(?:tests?|pytest|unittest|lint|ruff|flake8|mypy|eslint|tsc|check|gate|verify|upload|push|publish)\b", re.I)
BUILDX = re.compile(r"uses:\s*docker/setup-buildx-action@")
DRIVER_DOCKER = re.compile(r"^\s*driver:\s*['\"]?docker['\"]?\s*(#.*)?$")
UPLOAD = re.compile(r"uses:\s*actions/upload-artifact@")
ROOT_CAUSE = re.compile(r"#\s*root-cause:\s*t_[0-9a-f]{6,}")
# t_0deb6ad8: логин через демон = пинг ghcr.io/v2/ с жёстким 15s таймаутом -> context deadline exceeded.
# Замена: mytab0r/hermes-scripts/.github/actions/ghcr-login@main (креды в config.json клиента).
DAEMON_LOGIN = re.compile(r"uses:\s*docker/login-action@|\bdocker\s+login\b")
ARTIFACT_OK = re.compile(r"#\s*artifact-ok:\s*\S")


def _rules(line):
    if COE.match(line):
        yield "continue-on-error", ROOT_CAUSE
    m = OR_TRUE.search(line)
    if m and GATE.search(line[:m.start()]):
        yield "or-true", ROOT_CAUSE
    if DAEMON_LOGIN.search(line) and not line.lstrip().startswith("#"):
        yield "daemon-login", ROOT_CAUSE
    if UPLOAD.search(line):
        yield "upload-artifact", ARTIFACT_OK



def lint_text(text):
    lines, out = text.splitlines(), []
    for i, line in enumerate(lines):
        # t_a41372f5: эфемерный BuildKit (docker-container) качает базу с Docker Hub каждый прогон -> httpReadSeeker EOF
        if BUILDX.search(line) and not any(DRIVER_DOCKER.match(x) for x in lines[i + 1:i + 6]):
            ctx, j = [line], i - 1
            while j >= 0 and lines[j].strip().startswith("#"):
                ctx.append(lines[j]); j -= 1
            if not any(ROOT_CAUSE.search(c) for c in ctx):
                out.append((i + 1, "buildx-driver"))
        for rule, waiver in _rules(line):
            ctx, j = [line], i - 1
            while j >= 0 and lines[j].strip().startswith("#"):
                ctx.append(lines[j])
                j -= 1
            if not any(waiver.search(c) for c in ctx):
                out.append((i + 1, rule))
    return out


def main(root="."):
    root = pathlib.Path(root)
    files = sorted(p for ext in ("*.yml", "*.yaml") for p in (root / ".github/workflows").glob(ext))
    bad = 0
    for f in files:
        lines = f.read_text(encoding="utf-8").splitlines()
        for n, rule in lint_text("\n".join(lines)):
            print(f"{f.relative_to(root).as_posix()}:{n}: {rule}: {lines[n - 1].strip()}")
            bad += 1
    if bad:
        print(f"FAIL: {bad} обход(ов) без '# root-cause: t_<карточка>' / '# artifact-ok: <причина>' (ai-dev-engineering #25)", file=sys.stderr)
        return 1
    print(f"ok: {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
