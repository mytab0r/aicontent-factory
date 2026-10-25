# -*- coding: utf-8 -*-
"""t_522ca872: динамический loudnorm в lofi-ветке master() давит LRA («каша»).

Механизм (замеры 25.10, сегмент 180 с, жанр lofi):
  raw LRA 19.3 -> master() (динамический loudnorm LRA=11) -> LRA 1.6, I -17.2
  -> гейт: «LRA 1.6 < 3.5: динамика раздавлена». 11/14 прогонов теряли выпуск
  (0/N сегментов), медиана LRA забракованных — 2.6 при пороге 3.5.
  Статический volume + alimiter (-1.2 dBFS): LRA сохраняет, I в гейте,
  идемпотентно (двойной мастеринг банка put + release: 1x == 2x).

Plain script, no pytest. RED на старом коде: динамический loudnorm роняет
LRA 19.3 -> < 3.5. Фикстуры: «динамичный» сигнал (удар каждые 4 с, LRA ~20)
и «плоский» (ровный синус, LRA < 1) — плоский и должен остаться плоским
(гейт min_lra честно бракует генерацию без динамики; тест это разрешает).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import mastering  # noqa: E402
import quality_gate as qg  # noqa: E402


def il_lra(path):
    m = mastering.measure(str(path))
    return m["i"], m["lra"]


def make_dyn(out, dur=90):
    """Удар 0.2 с каждые 4 с над тихой подложкой — LRA ~20 (форма живого лоу-фая)."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
                    "-f", "lavfi", "-i", "sine=frequency=110:duration=3.8",
                    "-filter_complex",
                    "[0]volume=0.9[a];[1]volume=0.02[b];[a][b]concat=v=0:a=1[ab];"
                    f"[ab]aloop=loop={dur // 4}:size=1[out]",
                    "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "192k", str(out)], check=True)


def test_master_keeps_lra():
    """Главное: master() на динамичном raw обязан оставить LRA >= порога гейта,
    а громкость — в MIN_I..MAX_I (гейт не ослаблен)."""
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "dyn.mp3"
        make_dyn(raw)
        i0, lra0 = il_lra(raw)
        assert lra0 >= 15.0, f"фикстура недостаточно динамична: LRA {lra0}"
        out = Path(td) / "mastered.mp3"
        mastering.master(str(raw), str(out), genre="anime lofi")
        i1, lra1 = il_lra(out)
        assert lra1 >= qg.REF["lofi"]["min_lra"], \
            f"RED (динамический loudnorm): LRA {lra0} -> {lra1} < {qg.REF['lofi']['min_lra']} (каша)"
        assert qg.MIN_I <= i1 <= qg.MAX_I, f"громкость после master {i1} вне гейта"
        # повторный мастеринг (банк: put, потом release) не душит остаток динамики
        mastering.master(str(out), str(out), genre="anime lofi")
        i2, lra2 = il_lra(out)
        assert lra2 >= qg.REF["lofi"]["min_lra"], \
            f"двойной мастеринг: LRA {lra1} -> {lra2} (put+release)"
        print(f"dyn: LRA {lra0} -> {lra1} -> {lra2}, I {i1:.1f} -> {i2:.1f}")


def test_no_dynamic_loudnorm_in_lofi_path():
    """t_522ca872: в lofi-ветке master() loudnorm запрещён вовсе: динамический давит
    LRA до «каши», линейный молча возвращается к dynamic при усилении больше запаса
    до TP-потолка (замеры в шапке файла). Громкость = статический volume + alimiter."""
    src = (HERE / "mastering.py").read_text(encoding="utf-8")
    start = src.find("        m0 = measure(src)")
    end = src.find("\n    m = measure(dst)", start)
    lofi_branch = src[start:end]
    assert "loudnorm" not in lofi_branch, "loudnorm вернулся в lofi-ветку master()"
    assert "volume=" in lofi_branch, "статический volume отсутствует в lofi-ветке"
    assert "alimiter" in lofi_branch, "safety-лимитер отсутствует в lofi-ветке"


def test_flat_stays_gateable():
    """Плоский raw не должен ломать master(): выход существует, громкость в гейте.
    Плоскую генерацию бракует min_lra гейта — так и задумано, тут только цепочка."""
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "flat.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=330:duration=12:sample_rate=48000", str(raw)], check=True)
        out = Path(td) / "flat_m.mp3"
        mastering.master(str(raw), str(out), genre="anime lofi")
        i, lra = il_lra(out)
        assert qg.MIN_I <= i <= qg.MAX_I, f"громкость {i} вне гейта"
        print(f"flat: LRA {lra}, I {i:.1f}")


if __name__ == "__main__":
    test_master_keeps_lra()
    test_no_dynamic_loudnorm_in_lofi_path()
    test_flat_stays_gateable()
    print("test_master_lra OK")
