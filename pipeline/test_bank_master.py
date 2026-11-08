# -*- coding: utf-8 -*-
"""t_cron1024b: финальная склейка банка мастерится как сгенерированный микс (mastering.master +
fade_end). Без этого TP склейки > -1 dBTP (клиппинг, run 40087548227) — сегменты мастерились
поодиночке, concat перекодирует и поднимает пики; гейт 03c честно ловит. Гейт не ослаблен."""
import importlib.util
import re
import subprocess as sp
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, fn)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _br():
    return _load("bank_release_m", HERE / "bank_release.py")


def test_assemble_calls_master_final():
    br = _br()
    m = br._music_mod()
    calls = []
    m.prep_segments = lambda ps, log=print: calls.append("prep")
    m.concat_tracks = lambda ps, out, xfade=m.XFADE: (calls.append("concat"), ([0.0, 164.0], [172.0]))[1]
    m._probe_sec = lambda p: 180.0
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td)
        paths = [rd / "a.mp3", rd / "b.mp3"]
        for p in paths:
            p.write_bytes(b"x")
        metas = [{"name": "a", "seed": 1, "prompt": "p"}, {"name": "b", "seed": 2, "prompt": "p"}]
        try:
            br.master_final
        except AttributeError:
            raise AssertionError("master_final отсутствует: склейка банка не мастерится (TP > -1)")
        real = br.master_final
        br.master_final = lambda path, genre: calls.append(("master", Path(path).name, genre))
        try:
            br.assemble(paths, rd, metas, "anime lofi")
        finally:
            br.master_final = real
        assert ("master", "track.mp3", "anime lofi") in calls, calls


def test_master_final_tp_on_real_audio():
    """Реальный ffmpeg-звук: склейка с master_final держит пик ниже порога гейта (-0.9 dB, TP≈peak для синуса)."""
    for name in [n for n in list(sys.modules) if n.startswith("bank_release_m") or n == "acf_music03"]:
        del sys.modules[name]  # first test leaves concat/prep stubs cached - need a clean module
    br = _br()
    with tempfile.TemporaryDirectory() as td:
        segs = []
        for i in range(2):
            p = f"{td}/s{i}.mp3"
            sp.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=220:duration=180,volume=-1dB",
                    "-af", "afade=t=in:d=2,afade=t=out:st=172:d=6",
                    "-c:a", "libmp3lame", "-b:a", "192k", p], check=True)
            segs.append(Path(p))
        out = Path(td) / "track.mp3"
        try:
            br.master_final
        except AttributeError:
            raise AssertionError("master_final отсутствует: склейка банка не мастерится (TP > -1)")
        br.assemble(segs, Path(td), [{"name": f"s{i}", "seed": i, "prompt": "p"} for i in range(2)], "anime lofi")
        assert out.exists()
        e = sp.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(out),
                    "-af", "astats=measure_overall=Peak_level:measure_perchannel=none", "-f", "null", "-"],
                   capture_output=True, text=True).stderr
        peak = float(re.findall(r"Peak level dB: (-?[0-9.]+)", e)[-1])
        assert peak <= -0.9, f"Peak {peak} dB — выше порога гейта (TP примерно равен peak для синуса)"


def test_master_final_lufs_in_gate_on_peaky_audio():
    """t_2c32a785: выпуски банка -16.1..-16.5 LUFS = 03c FAIL «громкость вне -16..-13: YouTube-нормализация».
    loudnorm linear=true на пиковом треке (gain поднимает TP выше цели) молча уходил в динамический режим
    и недотягивал. Фикстура: тихий pink + бочка 55 Гц (I -23.5, TP -6). Старый код: I -18.4 FAIL.
    Цель и окно гейта из quality_gate (LUFS_TARGET/MIN_I/MAX_I)."""
    import quality_gate as qg
    import mastering
    br = _load("bank_release_lufs", HERE / "bank_release.py")
    br._music_mod = lambda: type("M", (), {"fade_end": staticmethod(lambda *a, **k: None)})
    with tempfile.TemporaryDirectory() as td:
        out = f"{td}/track.mp3"
        sp.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.05:d=60:r=48000",
                "-f", "lavfi", "-i", "aevalsrc='if(lt(mod(t,0.5),0.08),0.8*sin(2*PI*55*t)*exp(-30*mod(t,0.5)),0)':s=48000:d=60",
                "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0", "-ac", "2",
                "-c:a", "libmp3lame", "-b:a", "192k", out], check=True)
        assert mastering.measure(out)["i"] < qg.MIN_I - 2  # фикстура реально тихая
        br.master_final(out, "anime lofi")
        m = mastering.measure(out)
        assert qg.MIN_I <= m["i"] <= qg.MAX_I, f"громкость {m} вне {qg.MIN_I}..{qg.MAX_I}"
        assert abs(m["i"] - qg.LUFS_TARGET) <= br.LN_TOL + 0.2, m
        assert m["tp"] <= qg.MAX_TP, m


def test_master_final_lufs_in_gate_on_noisy_wall_audio():
    """t_32ee66e0 (run 40527578183): фикс t_2c32a785 закрыл единичную бочку раз в 0.5 с, но на
    phonk-"стене" (почти непрерывный белый шум с частыми резкими пиками каждые 0.5 с) I(gain) под
    лимитером немонотонна с ямой — фиксированный шаг gain += target-I застревал на -16.1..-16.5
    LUFS за LN_PASSES рендеров. Доп. регрессия: TP-доворот раньше шёл ПОСЛЕ выбора лучшего
    кандидата и мог утянуть I ниже гейта без повторной проверки — теперь доворот внутри кандидата,
    _next_gain бисектит по вилке вместо фикс. шага."""
    import quality_gate as qg
    import mastering
    br = _load("bank_release_lufs2", HERE / "bank_release.py")
    br._music_mod = lambda: type("M", (), {"fade_end": staticmethod(lambda *a, **k: None)})
    with tempfile.TemporaryDirectory() as td:
        out = f"{td}/track.mp3"
        src = "anoisesrc=c=white:a=0.95:d=60:r=48000,volume='if(lt(mod(t,0.5),0.01),1,0.01)':eval=frame"
        sp.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-ac", "2",
                "-c:a", "libmp3lame", "-b:a", "192k", out], check=True)
        assert mastering.measure(out)["i"] < qg.MIN_I  # фикстура реально тихая
        br.master_final(out, "chill phonk")
        m = mastering.measure(out)
        assert qg.MIN_I <= m["i"] <= qg.MAX_I, f"громкость {m} вне {qg.MIN_I}..{qg.MAX_I}"
        assert m["tp"] <= qg.MAX_TP, m


def _ln2_run(seq, passes):
    """loudnorm_2pass на 5-с синусе с подменённым mastering.measure (seq отыгрывается по порядку).
    Возвращает (j, хэши рендеров на момент замера, хэш dst, число ffmpeg-вызовов, остаток seq, temp-файлы)."""
    import hashlib
    import mastering
    br = _load("bank_release_tptrim", HERE / "bank_release.py")
    br.LN_PASSES = passes
    h = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    seen, calls = [], []
    def fake(p):
        seen.append(h(p))
        return seq.pop(0)
    real_m, real_run = mastering.measure, sp.run
    def run(cmd, *a, **k):
        if cmd and cmd[0] == "ffmpeg":
            calls.append(cmd)
        return real_run(cmd, *a, **k)
    with tempfile.TemporaryDirectory() as td:
        src, dst = f"{td}/src.mp3", f"{td}/dst.mp3"
        real_run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=5",
                  "-c:a", "libmp3lame", "-b:a", "192k", src], check=True)
        mastering.measure, sp.run = fake, run
        try:
            j = br.loudnorm_2pass(src, dst)
        finally:
            mastering.measure, sp.run = real_m, real_run
        left = [f.name for f in Path(td).iterdir() if f.name not in ("src.mp3", "dst.mp3")]
        return j, seen, (h(dst) if Path(dst).exists() else None), calls, seq, left


def test_loudnorm_2pass_keeps_best_when_later_pass_needs_tp_trim():
    """t_32ee66e0 review: TP-доворот писал вывод в `best` (файл лучшего кандидата) и уносил его в tmp.
    Лучший рендер первым + худший второй с TP выше TP_SAFE = `best` удалён -> FileNotFoundError."""
    from quality_gate import LUFS_TARGET as T
    seq = [{"tp": -4.0, "i": T - 0.9, "lra": 5},   # pass 1: TP ок (<=TP_SAFE), лучший (вне допуска -> pass 2)
           {"tp": -0.5, "i": T - 3.0, "lra": 5}]   # pass 2: TP выше TP_SAFE, хуже pass 1
    j, seen, dst_h, calls, rest, left = _ln2_run(seq, 2)
    assert not rest, f"сценарий не отыгран: {rest}"
    assert dst_h, "dst нет: лучший кандидат уничтожен"
    assert dst_h == seen[0], "в dst не рендер лучшего прохода"
    assert j["i"] == T - 0.9, j
    assert not left, f"temp-файлы остались: {left}"


def test_loudnorm_2pass_budget_and_final_tp_trim():
    """t_32ee66e0 (run 40612738736: 03 music timeout 20 мин): час = ~35 c рендер + ~20 c замер.\n    Бюджет: 1 рендер + 1 замер на проход, TP-доворот (рендер + замер, до 2 раз) только у итогового\n    кандидата. I после доворота учитывается при выборе (I + (TP_SAFE - TP - 0.1)), в j — замер после доворота.\n    Fix: LP_SAFE=TP=-3.0; подгонка TM= иclusive Гейт TF= -3.0, поэтому ассертации CL<= -3.0 на gp fixed, и fixture TP=-2.9, замер -3.0."""
    from quality_gate import LUFS_TARGET as T
    seq = [{"tp": -0.8, "i": T + 0.2, "lra": 5},   # доворот -0.5 дБ -> I T-0.3: в допуске, стоп
           {"tp": -1.3, "i": T - 0.3, "lra": 5}]   # замер после доворота
    j, seen, dst_h, calls, rest, left = _ln2_run(seq, 8)
    assert not rest, f"сценарий не отыгран: {rest}"
    assert len(calls) == 3, f"ebur128 + 1 рендер + 1 доворот, а не {len(calls)}"
    assert dst_h == seen[1], "в dst не доворот лучшего кандидата"
    assert j["i"] == T - 0.3, j
    assert not left, f"temp-файлы остались: {left}"
    # худший случай: LN_PASSES проходов + 2 доворота = ebur128 + LN_PASSES + 2 рендера.
    # Второй доворот тоже уходит в измеритель — каждый доворот is a render + a measure.
    import importlib
    seq = [{"tp": -0.1, "i": T - 6.0, "lra": 5} for _ in range(8)] + [{"tp": -0.9, "i": T - 7, "lra": 5},
                                                                      {"tp": -1.3, "i": T - 7, "lra": 5},
                                                                      {"tp": -1.4, "i": T - 7, "lra": 5},
                                                                      {"tp": -3.6, "i": T - 7, "lra": 5}]
    j, seen, dst_h, calls, rest, left = _ln2_run(seq, 8)
    assert not rest and dst_h and not left, (rest, left)
    assert len(calls) == 1 + 8 + 2, len(calls)
    assert len(seen) == 8 + 2 + 2, len(seen)


if __name__ == "__main__":  # t_110fa85f: CI запускает файл как скрипт — без блока def test_* не выполняются
    _fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for _f in _fns:
        _f()
        print("ok", _f.__name__)
    print(f"PASS {len(_fns)} tests")
