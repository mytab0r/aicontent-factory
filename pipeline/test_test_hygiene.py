#!/usr/bin/env python3
"""CI гоняет `python pipeline/test_X.py`: def test_ ниже блока if __name__ == "__main__" не выполняется
(19.10: test_trim_fade_tails был мёртв, trim_fade_tails в проде был no-op, стык R3 упал)."""
import ast
import re
from pathlib import Path


def dead_tests():
    bad = []
    for f in sorted(Path(__file__).resolve().parent.glob("test_*.py")):
        s = f.read_text(encoding="utf-8")
        m = re.search(r"^if __name__ == .__main__.:", s, re.M)
        # t_110fa85f: файл без блока __main__ тоже мёртв — CI гоняет `python test_X.py`,
        # def test_* без вызова не выполняются (тест t_bank_master так и не гонялся в CI).
        if re.search(r"^def test_", s, re.M) and (not m or re.search(r"^def test_", s[m.end():], re.M)):
            bad.append(f.name)
    return bad


def test_no_test_defined_after_main():
    assert dead_tests() == [], dead_tests()


def _is_redirect_cm(node):
    # `redirect_stdout(x)` / `redirect_stderr(x)`, с префиксом contextlib или без
    return (isinstance(node, ast.Call)
            and ((isinstance(node.func, ast.Name) and node.func.id in ("redirect_stdout", "redirect_stderr"))
                 or (isinstance(node.func, ast.Attribute) and node.func.attr in ("redirect_stdout", "redirect_stderr"))))


def _is_gate_main_call(node):
    # вызов qg.main(...) / quality_gate.main(...)
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == "main"
            and isinstance(node.func.value, ast.Name) and node.func.value.id in ("qg", "quality_gate"))


def leaky_gate_calls():
    """t_110fa85f / t_c6959421: негативные фикстуры через qg.main печатают `::error::quality gate: …`
    (true peak … клиппинг, «резкий конец») в лог CI, recurrence_scan принимает их за прод-дефекты
    (CI 39699460380/39827389930). Утечка = вызов qg.main/quality_gate.main НЕ внутри лексического
    `with redirect_stdout(...)/redirect_stderr(...)`. Проверяется каждый вызов через ast: старая
    подстрочная проверка («redirect_stdout» где-то в файле) пропускала новый незаглушённый вызов
    в файле, где redirect уже был, — ловила только удаление всех redirect разом."""
    me = Path(__file__).resolve()
    bad = []

    for f in sorted(me.parent.glob("test_*.py")):
        if f == me:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))

        def walk(node, captured):
            if node is None:
                return
            if isinstance(node, (ast.With, ast.AsyncWith)):
                redir = any(_is_redirect_cm(item.context_expr) for item in node.items)
                for item in node.items:
                    walk(item.context_expr, captured)
                    walk(item.optional_vars, captured)
                for child in node.body:
                    walk(child, captured or redir)
                return
            if _is_gate_main_call(node) and not captured:
                bad.append(f"{f.name}:{node.lineno}")
            for field in node._fields:
                child = getattr(node, field, None)
                if isinstance(child, ast.AST):
                    walk(child, captured)
                elif isinstance(child, list):
                    for sub in child:
                        if isinstance(sub, ast.AST):
                            walk(sub, captured)

        walk(tree, False)
    return bad


def test_gate_main_output_captured():
    assert leaky_gate_calls() == [], leaky_gate_calls()


if __name__ == "__main__":
    test_no_test_defined_after_main()
    print("ok test_no_test_defined_after_main")
    test_gate_main_output_captured()
    print("ok test_gate_main_output_captured")
