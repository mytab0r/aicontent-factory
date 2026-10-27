#!/usr/bin/env python3
"""CI-линт обходов гейтов («Повтор = класс», ai-dev-engineering #25).
FAIL на: setup-buildx-action без `driver: docker` (t_a41372f5) | continue-on-error: true | `|| true`/`|| :` после теста/гейта/upload/push | actions/upload-artifact (только текст, `# artifact-ok: <причина>, <N> KB|MB` < 10 МБ) | download-artifact (t_265d0147) | docker login / docker/login-action (t_831d9fd6).
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
# t_831d9fd6: `docker login` = daemon ping ghcr.io/v2/ с жёстким ~15s таймаутом через прокси Docker Desktop
# -> "Client.Timeout exceeded while awaiting headers". Креды писать в DOCKER_CONFIG, не логиниться демоном.
DOCKER_LOGIN = re.compile(r"uses:\s*docker/login-action@|\bdocker\s+login\b")
UPLOAD = re.compile(r"uses:\s*actions/upload-artifact@")
# t_0a4cae59: push образа неретраибельным экшеном (docker/build-push-action) или `docker buildx build --push`
# без retry-цикла ронял pay-image на разовых transport-обрывах egress ПК (EOF/timeout к ghcr).
BUILD_PUSH_ACTION = re.compile(r"uses:\s*docker/build-push-action@")
BUILDX_PUSH = re.compile(r"docker\s+buildx\s+build\b[^\n]*--push")
PULL_RETRY = re.compile(r"for n in 1 2 3 4.*docker pull|docker pull.*for n in 1 2 3 4")
PUSH_RETRY = re.compile(r"for n in 1 2 3 4")
ROOT_CAUSE = re.compile(r"#\s*root-cause:\s*t_[0-9a-f]{6,}")
ARTIFACT_OK = re.compile(r"#\s*artifact-ok:\s*\S")
# t_9d452170: каждый upload обязан иметь retention-days: 1 (квота storage 500MB/account; доставка вне артефактов)
RETENTION_1 = re.compile(r"^\s*retention-days:\s*['\"]?1['\"]?\s*(#.*)?$")
UPLOAD_CTX = 10  # между uses и retention бывают if:/continue-on-error: строки
# t_1011874c/t_265d0147: квота storage Free считается в ГБ-часах за месяц на весь аккаунт (500MB x 744h,
# общая с Packages); удаление/retention потраченное не возвращают (run 39395217149, 39363597218 упали на
# 'Artifact storage quota has been hit'). Медиа и передача между job — только C:\dockerlocal\acf-out\<run_id>\
# (deploy/gpu-pc/acf_out.sh). upload-artifact разрешён только с `# artifact-ok: <причина>, <N> KB|MB` (N < 10 МБ)
# и только текстовыми файлами (TEXT_EXT); download-artifact запрещён всегда.
DOWNLOAD = re.compile(r"uses:\s*actions/download-artifact@")
ARTIFACT_SIZE = re.compile(r"#\s*artifact-ok:.*?(\d+(?:[.,]\d+)?)\s*(KB|MB|КБ|МБ)\b", re.I)
SIZE_MAX_MB = 10
TEXT_EXT = re.compile(r"\.(?:json|jsonl|log|txt|md|csv)$")
PATH_KEY = re.compile(r"""^\s*(?:-\s*)?path:\s*(.*?)\s*(?:#.*)?$""")


def _rules(line, lines=None, i=0):
    if COE.match(line):
        yield "continue-on-error", ROOT_CAUSE
    m = OR_TRUE.search(line)
    if m and GATE.search(line[:m.start()]):
        yield "or-true", ROOT_CAUSE
    if DOCKER_LOGIN.search(line) and not line.lstrip().startswith("#"):
        yield "docker-login", ROOT_CAUSE
    if UPLOAD.search(line):
        if not any(RETENTION_1.match(x) for x in (lines or [])[i + 1:i + 1 + UPLOAD_CTX]):
            yield "upload-retention", ROOT_CAUSE
        yield "upload-artifact", ARTIFACT_OK
    if BUILD_PUSH_ACTION.search(line):
        # экшен-форма не ретраится целиком: transport-обрыв ghcr = красный workflow (t_0a4cae59)
        yield "push-no-retry", ROOT_CAUSE


# t_6758c86f: сетевой экшен (artifact/cache/setup-uv) на ПК-раннере без лимита висел до
# "exceeded the maximum execution time" джобы. Каждый такой шаг обязан иметь свой timeout-minutes.
NET_STEP = re.compile(r"^\s*-?\s*uses:\s*(?:actions/(?:upload-artifact|download-artifact|cache)(?:/restore|/save)?|astral-sh/setup-uv)@")


def lint_net_timeout(lines):
    out = []
    for i, line in enumerate(lines):
        if not NET_STEP.match(line):
            continue
        s = i
        while s > 0 and not lines[s].lstrip().startswith("- "):
            s -= 1
        ind, e = len(lines[s]) - len(lines[s].lstrip()), s + 1
        while e < len(lines) and (not lines[e].strip() or len(lines[e]) - len(lines[e].lstrip()) > ind):
            e += 1
        if not any(re.match(r"^\s*timeout-minutes:", x) for x in lines[s:e]):
            out.append((i + 1, "net-step-timeout"))
    return out


def lint_text(text):
    lines, out = text.splitlines(), []
    joined = "\n".join(lines)
    if BUILDX_PUSH.search(joined) and not PUSH_RETRY.search(joined):
        out.append((1, "push-no-retry"))
    if BUILDX_PUSH.search(joined) and not PULL_RETRY.search(joined):
        out.append((1, "push-no-prepull"))
    for i, line in enumerate(lines):
        # t_a41372f5: эфемерный BuildKit (docker-container) качает базу с Docker Hub каждый прогон -> httpReadSeeker EOF
        if BUILDX.search(line) and not any(DRIVER_DOCKER.match(x) for x in lines[i + 1:i + 6]):
            ctx, j = [line], i - 1
            while j >= 0 and lines[j].strip().startswith("#"):
                ctx.append(lines[j])
                j -= 1
            if not any(ROOT_CAUSE.search(c) for c in ctx):
                out.append((i + 1, "buildx-driver"))
        for rule, waiver in _rules(line, lines, i):
            ctx, j = [line], i - 1
            while j >= 0 and lines[j].strip().startswith("#"):
                ctx.append(lines[j])
                j -= 1
            if not any(waiver.search(c) for c in ctx):
                out.append((i + 1, rule))
    return out


def lint_branches(root="."):
    """t_de7348c1: workflow_dispatch берёт workflow С ТОЙ ВЕТКИ, что указана в ref. Устаревшая ветка `main`
    (default = master) хранила docker/login-action после фикса t_831d9fd6 -> dispatch ref=main снова дал
    "context deadline exceeded" от ghcr. Линт master/PR этого не видит. Здесь: docker-login на ЛЮБОЙ
    ветке origin = FAIL (ветку смержить с master или удалить)."""
    import subprocess
    git = lambda *a: subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, check=True).stdout
    bad = []
    for ref in git("for-each-ref", "--format=%(refname)", "refs/remotes/origin").split():
        if ref.endswith("/HEAD"):
            continue
        for path in git("ls-tree", "--name-only", f"{ref}:.github/workflows").split() if _has_wf(git, ref) else []:
            text = git("show", f"{ref}:.github/workflows/{path}")
            bad += [f"{ref}:{path}:{n}" for n, rule in lint_text(text) if rule == "docker-login"]
    return bad


def _has_wf(git, ref):
    try:
        git("rev-parse", "--verify", "-q", f"{ref}:.github/workflows")
        return True
    except Exception:
        return False


def _upload_paths(lines, i):
    """Пути upload-шага (inline или блок `path: |`/`>`) в пределах UPLOAD_CTX."""
    for j in range(i + 1, min(i + 1 + UPLOAD_CTX, len(lines))):
        m = PATH_KEY.match(lines[j])
        if not m:
            continue
        v = m.group(1).strip("'\"")
        if v and v[0] not in "|>":
            return [(j + 1, v)]
        ind, out = len(lines[j]) - len(lines[j].lstrip()), []
        for k in range(j + 1, len(lines)):
            if lines[k].strip() and len(lines[k]) - len(lines[k].lstrip()) <= ind:
                break
            item = lines[k].split("#")[0].strip().strip("'\"")
            if item and not item.startswith("!"):
                out.append((k + 1, item))
        return out
    return [(i + 1, "")]


def lint_artifacts(lines):
    """t_265d0147: download-artifact = FAIL; upload — только текст и объявленный размер < 10 МБ."""
    out = []
    for i, line in enumerate(lines):
        # t_265d0147: put без always() пропускается при падении джобы -> упавший прогон не оставляет файлов на C:
        if "acf_out.sh put" in line and not line.lstrip().startswith("#"):
            s = i
            while s > 0 and not lines[s].lstrip().startswith("- "):
                s -= 1
            if not any(re.match(r"^\s*if:.*\balways\(\)", x) for x in lines[s:i]):
                out.append((i + 1, "acf-out-always"))
        if DOWNLOAD.search(line) and not line.lstrip().startswith("#"):
            out.append((i + 1, "download-artifact"))
        if not UPLOAD.search(line) or line.lstrip().startswith("#"):
            continue
        ctx, j = [line], i - 1
        while j >= 0 and lines[j].strip().startswith("#"):
            ctx.append(lines[j])
            j -= 1
        m = next((ARTIFACT_SIZE.search(c) for c in ctx if ARTIFACT_SIZE.search(c)), None)
        mb = float(m.group(1).replace(",", ".")) / (1024 if m and m.group(2).upper() in ("KB", "КБ") else 1) if m else None
        if mb is None or mb >= SIZE_MAX_MB:
            out.append((i + 1, "upload-size"))
        out += [(n, "upload-media") for n, pth in _upload_paths(lines, i) if not TEXT_EXT.search(pth)]
    return out


def main(root="."):
    root = pathlib.Path(root)
    files = sorted(p for ext in ("*.yml", "*.yaml") for p in (root / ".github/workflows").glob(ext))
    bad = 0
    for f in files:
        lines = f.read_text(encoding="utf-8").splitlines()
        for n, rule in lint_text("\n".join(lines)) + lint_net_timeout(lines) + lint_artifacts(lines):
            print(f"{f.relative_to(root).as_posix()}:{n}: {rule}: {lines[n - 1].strip()}")
            bad += 1
    if bad:
        print(f"FAIL: {bad} обход(ов) без '# root-cause: t_<карточка>' / '# artifact-ok: <причина>' (ai-dev-engineering #25)", file=sys.stderr)
        return 1
    print(f"ok: {len(files)} files")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--branches"]:
        b = lint_branches(*sys.argv[2:3])
        print("\n".join(f"{x}: docker-login на ветке (dispatch ref=<ветка> вернёт ghcr timeout, t_de7348c1)" for x in b) or "ok: branches")
        sys.exit(1 if b else 0)
    sys.exit(main(*sys.argv[1:2]))
