#!/usr/bin/env python3
"""CI-линт обходов гейтов («Повтор = класс», ai-dev-engineering #25).
FAIL на: setup-buildx-action без `driver: docker` (t_a41372f5) | continue-on-error: true | `|| true`/`|| :` после теста/гейта/upload/push | actions/upload-artifact | docker login / docker/login-action (t_831d9fd6) | сумма timeout шагов >= timeout джобы (t_79ec2527).
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
# t_1011874c: квота storage считается в GB-часах за месяц (500MB x 744h, общая с Packages), retention-days: 1
# её не спасает: 53 загрузки loopgen-frames-full (path: каталог, до 0.8GB) съели ~1400 GB-h при бюджете 372.
# Поэтому: (1) path каталогом = FAIL, (2) upload-artifact разрешён только в workflow из ARTIFACT_ALLOW —
# новый upload = осознанное добавление сюда с причиной (кто скачивает артефакт).
UPLOAD_DIR = re.compile(r"""^\s*(?:-\s*)?path:\s*['"]?[^'"#\s|*]+/['"]?\s*(#.*)?$""")
PATH_BLOCK = re.compile(r"^\s*(?:-\s*)?path:\s*[|>][-+]?\s*(#.*)?$")
BLOCK_DIR = re.compile(r"""^\s+['"]?[^'"#\s*!]+/['"]?\s*(#.*)?$""")
# ponytail: каталог без завершающего `/` (path: runs/loopgen) не ловится — закрывает ARTIFACT_ALLOW (upload-not-allowed)
ARTIFACT_ALLOW = {
    "daily-video.yml",  # g1zm0_metrics.py качает video.mp4 для аудио-аудита
    "oneoff-loop-generate.yml",  # oneoff-loop-final.yml качает artifact loopgen
    "oneoff-loop-final.yml", "oneoff-generate-samples.yml", "oneoff-dd-samples.yml", "oneoff-ab-refpool.yml",
    "oneoff-mix-check.yml", "oneoff-shorts-proof.yml",  # ручные разовые прогоны (workflow_dispatch)
}


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


# t_79ec2527: "The job has exceeded the maximum execution time" (38886770624: 05 publish, 39132157308: measure)
# = шаг без своего бюджета доедал лимит джобы; GitHub убивал джобу без имени виновника. Механизм: сумма
# timeout-minutes шагов обязана быть МЕНЬШЕ timeout-minutes джобы — зависший шаг падает своим таймаутом
# (явная ошибка с именем шага, TG alert) раньше, чем джоба упрётся в общий лимит.
# ponytail: шаги без timeout-minutes в сумму не входят (их остаток покрывает запас); ужесточить — 5 мин на каждый.
JOB_TO = re.compile(r"^    timeout-minutes:\s*(\d+)")
STEP_TO = re.compile(r"^\s{6,}(?:-\s*)?timeout-minutes:\s*(\d+)")


def lint_job_budget(lines):
    out, jobs = [], [i for i, x in enumerate(lines) if re.match(r"^  [\w-]+:\s*(#.*)?$", x)]
    if "jobs:" not in lines:
        return out
    top = lines.index("jobs:")
    jobs = [i for i in jobs if i > top] + [len(lines)]
    for a, b in zip(jobs, jobs[1:]):
        job = next(((i, int(m.group(1))) for i in range(a, b) if (m := JOB_TO.match(lines[i]))), None)
        steps = sum(int(m.group(1)) for x in lines[a:b] if (m := STEP_TO.match(x)))
        if job and steps >= job[1]:
            out.append((job[0] + 1, f"job-budget(steps={steps}>={job[1]})"))
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
                ctx.append(lines[j]); j -= 1
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


def lint_upload_budget(name, lines):
    """t_1011874c: upload только в разрешённых workflow и без загрузки целого каталога."""
    out = []
    for i, line in enumerate(lines):
        if not UPLOAD.search(line):
            continue
        if name not in ARTIFACT_ALLOW:
            out.append((i + 1, "upload-not-allowed"))
        for j in range(i + 1, min(i + 1 + UPLOAD_CTX, len(lines))):
            if UPLOAD_DIR.match(lines[j]):
                out.append((j + 1, "upload-dir"))
            elif PATH_BLOCK.match(lines[j]):
                # `path: |` / `>`: каждый элемент блока — отдельный путь (ревью t_1011874c)
                ind = len(lines[j]) - len(lines[j].lstrip())
                for k in range(j + 1, len(lines)):
                    item = lines[k]
                    if item.strip() and len(item) - len(item.lstrip()) <= ind:
                        break
                    if BLOCK_DIR.match(item):
                        out.append((k + 1, "upload-dir"))
    return out


def main(root="."):
    root = pathlib.Path(root)
    files = sorted(p for ext in ("*.yml", "*.yaml") for p in (root / ".github/workflows").glob(ext))
    bad = 0
    for f in files:
        lines = f.read_text(encoding="utf-8").splitlines()
        for n, rule in lint_text("\n".join(lines)) + lint_net_timeout(lines) + lint_job_budget(lines) + lint_upload_budget(f.name, lines):
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
