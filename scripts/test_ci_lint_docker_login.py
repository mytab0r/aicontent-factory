"""t_831d9fd6: docker login (daemon ping ghcr.io/v2/, ~15s) роняла image-джобы на ПК-раннере. Линт обязан ловить."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ci_bypass_lint", ROOT / "scripts" / "ci_bypass_lint.py")
lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint)

assert lint.lint_text("      - uses: docker/login-action@v3\n") == [(1, "docker-login")]
assert lint.lint_text("        run: echo x | docker login ghcr.io -u a --password-stdin\n") == [(1, "docker-login")]
assert lint.lint_text("      # root-cause: t_831d9fd6\n      - uses: docker/login-action@v3\n") == []
assert lint.lint_text("      # docker login is not used here\n") == []
# t_9d452170: upload без retention-days: 1 обязан ронять линт
assert lint.lint_text("      - uses: actions/upload-artifact@v4\n        with:\n          name: x\n          path: out/\n") == [(1, "upload-retention"), (1, "upload-artifact")]
assert lint.lint_text("      - uses: actions/upload-artifact@v4\n        with:\n          name: x\n          path: out/\n          retention-days: 1\n") == [(1, "upload-artifact")]
assert lint.lint_text("      # artifact-ok: x\n      # root-cause: t_9d452170\n      - uses: actions/upload-artifact@v4\n        with:\n          name: x\n          path: out/\n") == []
# t_0a4cae59: push без retry-механики обязан ронять линт
assert lint.lint_text("      - uses: docker/build-push-action@v6\n        with:\n          push: true\n") == [(1, "push-no-retry")]
assert lint.lint_text("      # root-cause: t_0a4cae59\n      - uses: docker/build-push-action@v6\n") == []
no_retry = "run: docker buildx build --push -t ghcr.io/x/y:latest .\n"
got = lint.lint_text(no_retry)
assert (1, "push-no-retry") in got and (1, "push-no-prepull") in got, got
with_retry = "run: |\n  for n in 1 2 3 4; do docker pull -q \"$B\" && break; done\n  for n in 1 2 3 4; do docker buildx build --push -t ghcr.io/x/y:latest . && exit 0; done\n"
assert lint.lint_text(with_retry) == [], lint.lint_text(with_retry)
# t_6758c86f: сетевой шаг без timeout-minutes = FAIL
assert (1, "net-step-timeout") in lint.lint_net_timeout("      - uses: astral-sh/setup-uv@v3\n      - name: x\n        run: y\n".splitlines())
assert (1, "net-step-timeout") in lint.lint_net_timeout("      - uses: actions/cache/restore@v4\n        with:\n          path: a\n".splitlines())
assert not [x for x in lint.lint_net_timeout("      - name: a\n        uses: actions/cache@v4\n        timeout-minutes: 15\n        with:\n          path: a\n".splitlines()) if x[1] == "net-step-timeout"]
# t_de7348c1: устаревшая ветка с docker/login-action обязана ронять --branches
import subprocess, tempfile
with tempfile.TemporaryDirectory() as d:
    g = lambda *a: subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)
    g("init", "-q"); pathlib.Path(d, ".github/workflows").mkdir(parents=True)
    pathlib.Path(d, ".github/workflows/img.yml").write_text("      - uses: docker/login-action@v3\n")
    g("add", "-A"); g("commit", "-qm", "x"); g("update-ref", "refs/remotes/origin/main", "HEAD")
    assert lint.lint_branches(d) == ["refs/remotes/origin/main:img.yml:1"], lint.lint_branches(d)
    pathlib.Path(d, ".github/workflows/img.yml").write_text("      - run: echo ok\n")
    g("commit", "-qam", "fix"); g("update-ref", "refs/remotes/origin/main", "HEAD")
    assert lint.lint_branches(d) == []
# t_265d0147: квота storage в ГБ-часах — медиа/каталог/без размера/>=10 МБ/download-artifact обязаны ронять линт
A = lint.lint_artifacts
up = "      - uses: actions/upload-artifact@v4  # artifact-ok: {}\n        with:\n          retention-days: 1\n          path: {}\n"
assert A(up.format("отчёт, 40 KB", "out/report.json").splitlines()) == []
assert A(up.format("лог, 2 МБ", "out/run.log").splitlines()) == []
assert A(up.format("отчёт", "out/report.json").splitlines()) == [(1, "upload-size")]
assert A(up.format("отчёт, 10 MB", "out/report.json").splitlines()) == [(1, "upload-size")]
assert A(up.format("отчёт, 12000 KB", "out/report.json").splitlines()) == [(1, "upload-size")]
assert A(up.format("видео, 5 MB", "runs/*/video.mp4").splitlines()) == [(4, "upload-media")]
assert A(up.format("каталог, 5 MB", "runs/loopgen/").splitlines()) == [(4, "upload-media")]
assert A(up.format("всё, 5 MB", "out/*  # x").splitlines()) == [(4, "upload-media")]
blk = "      # artifact-ok: логи, 1 MB\n      - uses: actions/upload-artifact@v4\n        with:\n          path: |\n            a.json\n            runs/x.mp3\n            !b.mp3\n      - name: next\n        run: echo a.mp4\n"
assert A(blk.splitlines()) == [(6, "upload-media")], A(blk.splitlines())
assert A(blk.replace("path: |", "path: >-").splitlines()) == [(6, "upload-media")]
assert A("      - uses: actions/download-artifact@v4\n".splitlines()) == [(1, "download-artifact")]
assert A("      # actions/download-artifact@v4 убран\n".splitlines()) == []
assert (1, "upload-artifact") in lint.lint_text("      - uses: actions/upload-artifact@v4\n        with:\n          retention-days: 1\n")
assert lint.main(str(ROOT)) == 0
print("ok")
