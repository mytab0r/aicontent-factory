"""t_a41372f5: setup-buildx-action без `driver: docker` = эфемерный BuildKit, база с Docker Hub каждый прогон
-> httpReadSeeker unexpected EOF. Линт обязан ловить, реальные workflows обязаны быть чистыми."""
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from ci_bypass_lint import lint_text, main

assert lint_text("      - uses: docker/setup-buildx-action@v3\n      - uses: x") == [(1, "buildx-driver")]
assert lint_text("      - uses: docker/setup-buildx-action@v3\n        with:\n          driver: docker\n") == []
assert lint_text("      - uses: docker/setup-buildx-action@v3\n        with:\n          driver: docker-container\n") == [(1, "buildx-driver")]
assert lint_text("      # root-cause: t_a41372f5\n      - uses: docker/setup-buildx-action@v3\n") == []
assert main(str(ROOT)) == 0
print("ok")
