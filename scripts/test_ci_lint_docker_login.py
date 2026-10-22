"""t_831d9fd6: docker login (daemon ping ghcr.io/v2/, ~15s) роняла image-джобы на ПК-раннере. Линт обязан ловить."""
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from ci_bypass_lint import lint_text, main

assert lint_text("      - uses: docker/login-action@v3\n") == [(1, "docker-login")]
assert lint_text("        run: echo x | docker login ghcr.io -u a --password-stdin\n") == [(1, "docker-login")]
assert lint_text("      # root-cause: t_831d9fd6\n      - uses: docker/login-action@v3\n") == []
assert lint_text("      # docker login is not used here\n") == []
assert main(str(ROOT)) == 0
print("ok")
