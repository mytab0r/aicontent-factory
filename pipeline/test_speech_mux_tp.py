#!/usr/bin/env python3
"""t_f5e84e62: сторожевой тест класса «клиппинг после AAC-кодера».

Причина (факт, run 40408005493 + замеры ниже): лимитер/loudnorm стоят ДО AAC-кодера, а кодер
поднимает true peak выше своего потолка. Замер на фикстуре ВЧ-транзиентов: WAV после
alimiter -1.5 -> +3.8 dBTP после aac 192k. Гейт (MAX_TP -1.0) видит это уже в финальном mp4.
04_assemble починили (t_fef617d9), но те же пути в 07_shorts / owning_channel / whatif_channel
остались на «aac прямо в mux» — там овершут никто не мерил.

Сторож падает, если: (1) финальный mux любого пути снова кодирует звук сам вместо замера TP
после кодера; (2) звук горячей фикстуры после реального пути рендера выходит выше SPEECH_TP_MAX;
(3) сам механизм перестал опускать потолок.
"""
import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import quality_gate as qg  # noqa: E402

# Горячая фикстура: ВЧ-транзиенты, на которых AAC даёт межсэмпловый овершут.
# Замер: старый путь 07_shorts (loudnorm TP=-1.5 + aac 192k в mux) даёт на ней -1.4 dBTP,
# гейт речи требует <= -1.6 -> реальный RED, не синтетика.
HOT = ("aevalsrc=0.99*sgn(sin(2*PI*11000*t))*exp(-90*mod(t\\,0.06))"
       "+0.3*sgn(sin(2*PI*19000*t))*exp(-90*mod(t\\,0.06)):s=44100:d=8")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, HERE / path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _hot(path):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", HOT,
                    "-c:a", "libmp3lame", "-b:a", "192k", str(path)], check=True)
    return path


def test_mechanism_fixes_codec_overshoot():
    """RED на наивном пути: alimiter -1.5 + aac 192k даёт TP выше гейта; encode_aac_tp держит потолок."""
    with tempfile.TemporaryDirectory() as td:
        w, naive, fixed = Path(td) / "h.wav", Path(td) / "n.m4a", Path(td) / "f.m4a"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", HOT,
                        "-c:a", "pcm_s16le", str(w)], check=True)
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(w),
                        "-af", "alimiter=limit=-1.5dB:level=false", "-c:a", "aac", "-b:a", "192k", str(naive)],
                       check=True)
        assert qg.tp_of(naive) > qg.SPEECH_TP_MAX, f"фикстура не воспроизводит овершут кодера: {qg.tp_of(naive)}"
        tp = qg.encode_aac_tp(w, fixed, "192k", qg.SPEECH_TP_MAX)
        assert tp <= qg.SPEECH_TP_MAX and abs(qg.tp_of(fixed) - tp) < 0.05, (tp, qg.tp_of(fixed))


def test_no_raw_aac_in_final_mux():
    """Финальный mux не кодирует звук сам: AAC только через encode_aac_tp (замер после кодера).
    Промежуточные рендеры (сегменты сцен/реплик) кодировать AAC могут — их звук всё равно
    проходит финальный loudnorm+encode_aac_tp. Правило: блок ffmpeg с "-c:a copy" не содержит "-c:a aac",
    и такой блок в файле есть."""
    for name in ("04_assemble.py", "07_shorts.py", "owning_channel.py", "whatif_channel.py"):
        src = (HERE / name).read_text(encoding="utf-8")
        assert "encode_aac_tp" in src, f"{name}: финальный звук не проходит encode_aac_tp"
        copies = [b for b in src.split("subprocess.run(") if '"-c:a", "copy"' in b]
        assert copies, f"{name}: финальный mux больше не копирует проверенный AAC (-c:a copy пропал)"
        bad = [b[:120] for b in copies if re.search(r'"-c:a",\s*"aac"', b)]
        assert not bad, f"{name}: финальный mux снова кодирует звук сам (TP после кодера не меряется): {bad}"


def test_shorts_render_tp_below_gate():
    """Реальный путь 07_shorts.render на горячей фикстуре: TP шортса в пределах SPEECH_TP_MAX."""
    from PIL import Image
    sh = _load("shorts_tp", "07_shorts.py")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        Image.new("RGB", (640, 360), (30, 30, 60)).save(d / "cover.png")
        _hot(d / "track.mp3")
        out = d / "short.mp4"
        sh.render(d / "cover.png", d / "track.mp3", 0.0, 6.0, out)
        tp = qg.tp_of(out)
        print(f"shorts render TP={tp:+.1f}")
        assert tp <= qg.SPEECH_TP_MAX, f"07_shorts: TP {tp:+.1f} > {qg.SPEECH_TP_MAX}"


def test_whatif_concat_tp_below_gate():
    """Реальный путь whatif_channel.concat (склейка сцен): TP результата в пределах SPEECH_TP_MAX."""
    wi = _load("whatif_tp", "whatif_channel.py")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        parts = []
        for i in range(2):
            p = d / f"s{i}.mp4"
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                            "-f", "lavfi", "-i", "color=c=black:s=320x240:r=10:d=3",
                            "-f", "lavfi", "-i", HOT, "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "128k", str(p)], check=True)
            parts.append(p)
        out = wi.concat(parts, d / "long.mp4")
        tp = qg.tp_of(out)
        print(f"whatif concat TP={tp:+.1f}")
        assert tp <= qg.SPEECH_TP_MAX, f"whatif concat: TP {tp:+.1f} > {qg.SPEECH_TP_MAX}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print(f.__name__, "OK")
    print(f"{len(fns)}/{len(fns)} passed")
