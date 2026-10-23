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
assert lint.main(str(ROOT)) == 0
print("ok")
