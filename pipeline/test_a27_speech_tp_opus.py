#!/usr/bin/env python3
"""A27: true peak речевого мастера с запасом на Opus YouTube. Регрессия на цифрах 26.10:
YouTube-копии K5cqI_AX4hk -0.3 и kQauDNrBAWU -0.8 dBTP; мастер около -1.1 проходил старый гейт (MAX_TP -1.0)."""
import pathlib, shutil, subprocess, sys, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import quality_gate as qg


def _mk(out, peak_db):
    # синус с точным пиком: loudnorm на шуме не попадает в TP (CI 26.10: цель -1.1 дала -1.8)
    a = 10 ** (peak_db / 20)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"aevalsrc={a:.4f}*sin(2*PI*440*t):s=48000:d=6", "-c:a", "pcm_s16le", str(out)], check=True)
    return out


def _tp(f):
    import re
    return float(re.findall(r"Peak:\s+(-?[\d.]+)", qg.ff(f, "ebur128=peak=true"))[-1])


def test_speech_tp_margin_constant():
    assert qg.SPEECH_TP_MAX <= -1.6, qg.SPEECH_TP_MAX  # не ослаблять


def test_speech_master_without_headroom_fails():
    if not shutil.which("ffmpeg"):
        print("skip: нет ffmpeg")
        return
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        thin = _mk(d / "thin.wav", -1.3)   # как мастер до A26: проходил MAX_TP -1.0, на YouTube -0.3..-0.8
        ok = _mk(d / "ok.wav", -2.0)       # мастер A26
        assert -1.6 < _tp(thin) <= qg.MAX_TP, _tp(thin)  # фикстура: старый гейт её пропускал
        assert any("true peak" in w for w in qg.speech_why(thin)), qg.speech_why(thin)
        assert not any("true peak" in w for w in qg.speech_why(ok)), (_tp(ok), qg.speech_why(ok))


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
