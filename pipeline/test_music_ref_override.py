"""Регресс: dd-ветка main() падала UnboundLocalError ref_override (22.10)."""
import ast
from pathlib import Path


def test_ref_override_bound_before_branches():
    src = (Path(__file__).parent / "03_music.py").read_text(encoding="utf-8")
    main = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    first_if = next(i for i, n in enumerate(main.body) if isinstance(n, ast.If))
    assigned = [n for n in main.body[:first_if] if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "ref_override" for t in n.targets)]
    assert assigned, "ref_override must be initialised before channel/genre branches"


if __name__ == "__main__":
    test_ref_override_bound_before_branches()
    print("ok")
