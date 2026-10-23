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
assert lint.main(str(ROOT)) == 0
print("ok")
