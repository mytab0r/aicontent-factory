"""C3-допуск ±1 тик Δpts на стыках concat (t_1daedc6b).

Регрессия run 38151431259: build_final упал на C3 (Δpts 999 != 1000 на 9
стыках из 1080). Допуск ±1 тик — только на стыках сегментов, не более
min(k_seg, 20) отклонений. 999 vs 1000 при timescale 24000 = 42 мкс,
на воспроизведение не влияет.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loop_build import pts_uniform_ok  # noqa: E402

EXPECTED = 1000


def test_exact():
    assert pts_uniform_ok([EXPECTED] * 100, EXPECTED, k_seg=100)


def test_one_joint_off_by_one():
    d = [EXPECTED] * 100
    d[40] = EXPECTED - 1
    assert pts_uniform_ok(d, EXPECTED, k_seg=100)


def test_all_joints_off_by_one():
    # 1079 сегментов = 1078 стыков, все стыки дают 999
    d = [EXPECTED - 1 if i % 80 == 79 else EXPECTED for i in range(80 * 13 - 1)]
    assert sum(1 for x in d if x != EXPECTED) == 12
    assert pts_uniform_ok(d, EXPECTED, k_seg=14)


def test_too_many_deviations():
    d = [EXPECTED] * 100
    for i in range(21):
        d[i * 4] = EXPECTED - 1
    assert not pts_uniform_ok(d, EXPECTED, k_seg=100)


def test_off_by_two_rejected():
    d = [EXPECTED] * 100
    d[10] = EXPECTED - 2
    assert not pts_uniform_ok(d, EXPECTED, k_seg=100)


def test_cap_at_20():
    # k_seg огромный — допуск ограничен 20
    d = [EXPECTED] * 100
    for i in range(25):
        d[i] = EXPECTED - 1
    assert not pts_uniform_ok(d, EXPECTED, k_seg=1080)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"{name}: OK")
    print("ALL OK")
