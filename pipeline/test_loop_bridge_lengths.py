"""Контракт длин M-моста: узел 22 (passA) = (m-1)*4+1, узел 12 (passB) = length - n_a + 2.

Регрессия run 38139330633: node12 получил {{LENGTH}}=81, assemble ожидал 54 —
passB: 81 кадров, ожидалось 54.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
from loop_generate import WORKFLOW  # noqa: E402


def test_bridge_lengths():
    tpl = json.loads(WORKFLOW.read_text())
    nodes = tpl["nodes"]
    assert nodes["22"]["inputs"]["length"] == "{{PALENGTH}}", "passA длина"
    assert nodes["12"]["inputs"]["length"] == "{{PBLENGTH}}", "passB длина"

    length, m_latent = 81, 8
    n_a = (m_latent - 1) * 4 + 1                      # 29 кадров passA
    pb = length - n_a + 2                             # 54 кадра passB
    from loop_generate import pb_pixels
    assert pb_pixels(length, m_latent) == 57          # 4*15-3, ближайшее >= 54
    assert pb_pixels(length, m_latent) >= pb
    filled = {
        "{{PALENGTH}}": n_a,
        "{{PBLENGTH}}": pb,
    }
    assert filled["{{PALENGTH}}"] == 29
    assert filled["{{PBLENGTH}}"] == 54
    # склейка: passA[1:] (28) + passB[1:] (53) == length
    assert (n_a - 1) + (pb - 1) == length


if __name__ == "__main__":
    test_bridge_lengths()
    print("OK")
